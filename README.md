# waldur-site-agent-openstack

Plugin OpenStack pour [waldur-site-agent](https://github.com/waldur/waldur-site-agent) permettant la synchronisation en temps réel des utilisateurs entre Waldur et OpenStack Keystone.

## 🎯 Fonctionnalités

- ✅ **Synchronisation temps réel** : Événements STOMP pour synchronisation instantanée
- ✅ **Gestion des utilisateurs** : Création automatique des utilisateurs OpenStack
- ✅ **Attribution des rôles** : Assignation automatique des rôles dans les projets
- ✅ **Gestion des projets** : Création/suppression de projets OpenStack
- ✅ **Production-ready** : Déploiement Kubernetes/k3s avec secrets management
- ✅ **Retry automatique** : Gestion des échecs avec exponential backoff

## 📋 Prérequis

- Python 3.9+
- OpenStack avec Keystone API v3
- waldur-site-agent >= 0.7.0
- Accès admin à OpenStack Keystone
- (Optionnel) Cluster Kubernetes ou k3s pour le déploiement

## 🏗️ Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    WALDUR CORE                               │
│           (Interface web + API + STOMP broker)              │
└────────────────────────┬────────────────────────────────────┘
                         │ Événements STOMP:
                         │ - offering_user_added
                         │ - offering_user_removed
                         │ - resource_created
                         │ - resource_terminated
            ┌────────────▼────────────┐
            │  waldur-site-agent       │
            │  Mode: event-process     │  ← UN agent par site
            │                          │
            │  Lit: config.yaml        │
            │  Traite: TOUS offerings  │
            └────────────┬────────────┘
                         │
            ┌────────────▼────────────┐
            │  OpenStackBackend        │
            │  (Notre plugin)          │
            │                          │
            │  - add_users_to_resource │
            │  - remove_users_...      │
            │  - create_resource       │
            │  - delete_resource       │
            └────────────┬────────────┘
                         │
            ┌────────────▼────────────┐
            │  KeystoneClient          │
            │  (python-keystoneclient) │
            └────────────┬────────────┘
                         │
            ┌────────────▼────────────┐
            │   OpenStack Keystone     │
            │   (API v3)               │
            └──────────────────────────┘
```

### Points clés de l'architecture

1. **UN agent par site** : L'agent tourne en un seul mode à la fois
2. **Configuration centralisée** : Fichier `waldur-site-agent-config.yaml`
3. **Backend reçoit `backend_settings`** : Pas de variables d'environnement directes
4. **Event processing** : Synchronisation temps réel via STOMP

## 🚀 Installation

### Installation locale (développement)

⚠️ **Note importante** : Le plugin est un package **séparé** de waldur-site-agent. Vous n'avez PAS besoin d'installer waldur-site-agent localement pour développer le plugin.

```bash
# Cloner le dépôt du plugin
git clone <repository-url>
cd owsa-agent

# Créer un environnement virtuel (recommandé)
uv venv
source .venv/bin/activate  # ou: .venv\Scripts\activate sur Windows

# Installer le plugin en mode éditable
uv pip install -e .

# Vérifier que le plugin est découvert
python -c "from importlib.metadata import entry_points; \
  eps = list(entry_points(group='waldur_site_agent.backends')); \
  print([ep.name for ep in eps if ep.name == 'openstack'])"
# Devrait afficher: ['openstack']
```

Pour tester localement, vous aurez besoin de waldur-site-agent:
```bash
# Dans le même venv
uv pip install git+https://github.com/waldur/waldur-site-agent.git@main
```

### Installation sur Kubernetes/k3s

Voir la section [Déploiement Kubernetes](#-déploiement-kuberneteskubernetes-k3s).

## ⚙️ Configuration

### 1. Créer le fichier de configuration

Créez `/etc/waldur-agent/config.yaml` (ou utilisez l'exemple dans `examples/`):

```yaml
offerings:
  - # Connexion Waldur
    waldur_api_url: "https://waldur.example.com/api"
    waldur_api_token: "${WALDUR_API_TOKEN}"  # Depuis variable d'environnement
    waldur_offering_uuid: "your-offering-uuid"

    # Backend OpenStack
    backend_type: "openstack"

    # Configuration OpenStack Keystone
    backend_settings:
      auth_url: "https://keystone.example.com:5000/v3"
      username: "admin"
      password: "${OPENSTACK_PASSWORD}"
      project_name: "admin"
      domain_name: "Default"
      default_role: "_member_"
      create_users_if_not_exist: true
      sync_user_emails: true

    # Backends par fonction
    membership_sync_backend: "openstack"
    order_processing_backend: "openstack"

    # Configuration STOMP (événements temps réel)
    stomp_enabled: true
    stomp_host: "waldur.example.com"
    stomp_port: 61613
    stomp_username: "agent"
    stomp_password: "${STOMP_PASSWORD}"
```

### 2. Configurer les variables d'environnement

```bash
export WALDUR_API_TOKEN="your-waldur-api-token"
export OPENSTACK_PASSWORD="your-openstack-admin-password"
export STOMP_PASSWORD="your-stomp-password"
```

### 3. Lancer l'agent

#### Mode event-process (temps réel, recommandé)

```bash
waldur-site-agent run --mode event-process --config /etc/waldur-agent/config.yaml
```

L'agent se connecte au broker STOMP et traite les événements en temps réel.

#### Mode membership-sync (polling périodique)

```bash
waldur-site-agent run --mode membership-sync --config /etc/waldur-agent/config.yaml
```

Utile pour :
- Backup de sécurité (via cron)
- Synchronisation initiale
- Réconciliation périodique

## 🐳 Déploiement Kubernetes/k3s

### Prérequis

- Cluster Kubernetes ou k3s
- kubectl configuré

### Déploiement rapide

```bash
# 1. Builder l'image Docker
cd /home/ahcene/work/owsa-agent
docker build -t waldur-site-agent-openstack:0.1.0 .

# 2. Charger l'image dans k3s
docker save waldur-site-agent-openstack:0.1.0 | sudo k3s ctr images import -

# 3. Créer le namespace
kubectl create namespace waldur-agent

# 4. Créer les secrets
kubectl create secret generic waldur-agent-secrets \
  --from-literal=WALDUR_API_TOKEN='your-waldur-token' \
  --from-literal=OPENSTACK_PASSWORD='your-openstack-password' \
  --from-literal=STOMP_PASSWORD='your-stomp-password' \
  -n waldur-agent

# 5. Éditer la ConfigMap avec vos valeurs
vim kubernetes/configmap.yaml
# Remplacer:
# - waldur.example.com → votre Waldur
# - keystone.example.com → votre OpenStack
# - your-openstack-offering-uuid-here → UUID réel

# 6. Appliquer la ConfigMap
kubectl apply -f kubernetes/configmap.yaml

# 7. 🎯 ÉTAPE CRITIQUE : Setup initial (UNE FOIS)
kubectl apply -f kubernetes/setup-job.yaml
kubectl logs -f job/waldur-load-components -n waldur-agent
# Attendre "Complete" avant de continuer

# 8. Déployer l'agent principal
kubectl apply -f kubernetes/deployment.yaml

# 9. Vérifier le déploiement
kubectl get pods -n waldur-agent
kubectl logs -f deployment/waldur-site-agent-openstack -n waldur-agent
```

**⚠️ Important** : Le Job `waldur-load-components` (étape 7) configure l'offering dans Waldur avec les composants définis (cpu, ram, etc.). Il DOIT être exécuté avec succès avant de déployer l'agent.

### Architecture du déploiement

```
┌──────────────────────────────────────────┐
│          Namespace: waldur-agent          │
│                                           │
│  ┌────────────────────────────────────┐  │
│  │  Deployment (replicas: 1)          │  │
│  │  ┌──────────────────────────────┐  │  │
│  │  │ Pod: waldur-site-agent       │  │  │
│  │  │                               │  │  │
│  │  │ Mode: event-process          │  │  │
│  │  │ Config: /etc/waldur-agent/   │  │  │
│  │  └──────────────────────────────┘  │  │
│  └────────────────────────────────────┘  │
│                                           │
│  ┌────────────────────────────────────┐  │
│  │  ConfigMap: waldur-agent-config    │  │
│  │  - config.yaml (non-sensible)      │  │
│  └────────────────────────────────────┘  │
│                                           │
│  ┌────────────────────────────────────┐  │
│  │  Secret: waldur-agent-secrets      │  │
│  │  - WALDUR_API_TOKEN               │  │
│  │  - OPENSTACK_PASSWORD             │  │
│  │  - STOMP_PASSWORD                 │  │
│  └────────────────────────────────────┘  │
│                                           │
│  ┌────────────────────────────────────┐  │
│  │  CronJob (optionnel): backup-sync  │  │
│  │  Schedule: "0 * * * *" (1x/heure)  │  │
│  └────────────────────────────────────┘  │
└──────────────────────────────────────────┘
```

### Gestion des secrets (production)

Pour la production, utilisez l'une de ces méthodes sécurisées :

#### Option 1 : Sealed Secrets

```bash
# Installer Sealed Secrets
kubectl apply -f https://github.com/bitnami-labs/sealed-secrets/releases/download/v0.24.0/controller.yaml

# Sceller un secret
kubectl create secret generic waldur-agent-secrets \
  --from-literal=WALDUR_API_TOKEN='...' \
  --dry-run=client -o yaml | \
kubeseal -o yaml > sealed-secret.yaml

# Commiter sealed-secret.yaml (il est chiffré!)
git add sealed-secret.yaml
git commit -m "Add sealed secrets"
```

#### Option 2 : External Secrets Operator

```yaml
apiVersion: external-secrets.io/v1beta1
kind: ExternalSecret
metadata:
  name: waldur-agent-secrets
  namespace: waldur-agent
spec:
  refreshInterval: 1h
  secretStoreRef:
    name: vault-backend
    kind: SecretStore
  target:
    name: waldur-agent-secrets
  data:
  - secretKey: WALDUR_API_TOKEN
    remoteRef:
      key: waldur/credentials
      property: api_token
```

## 📊 Monitoring et Logs

### Vérifier les logs

```bash
# Logs en temps réel
kubectl logs -f deployment/waldur-site-agent-openstack -n waldur-agent

# Logs des 100 dernières lignes
kubectl logs --tail=100 deployment/waldur-site-agent-openstack -n waldur-agent

# Logs d'un pod spécifique
kubectl logs waldur-site-agent-openstack-xxx-yyy -n waldur-agent
```

### État de l'agent

```bash
# État des pods
kubectl get pods -n waldur-agent

# Détails du déploiement
kubectl describe deployment waldur-site-agent-openstack -n waldur-agent

# Événements récents
kubectl get events -n waldur-agent --sort-by='.lastTimestamp'
```

## 🔧 Maintenance

### Mettre à jour la configuration

```bash
# 1. Éditer la ConfigMap
kubectl edit configmap waldur-agent-config -n waldur-agent

# 2. Redémarrer l'agent pour appliquer les changements
kubectl rollout restart deployment waldur-site-agent-openstack -n waldur-agent
```

### Mettre à jour les secrets

```bash
# Créer le nouveau secret
kubectl create secret generic waldur-agent-secrets \
  --from-literal=WALDUR_API_TOKEN='new-token' \
  --from-literal=OPENSTACK_PASSWORD='new-password' \
  --from-literal=STOMP_PASSWORD='new-stomp-password' \
  --dry-run=client -o yaml | kubectl apply -f -

# Redémarrer pour prendre en compte
kubectl rollout restart deployment waldur-site-agent-openstack -n waldur-agent
```

### Dépannage

```bash
# Accéder au shell du pod
kubectl exec -it deployment/waldur-site-agent-openstack -n waldur-agent -- /bin/bash

# Tester la connectivité OpenStack
kubectl exec -it deployment/waldur-site-agent-openstack -n waldur-agent -- \
  openstack --os-auth-url https://keystone.example.com:5000/v3 \
            --os-username admin \
            --os-password xxx \
            project list

# Vérifier la configuration montée
kubectl exec -it deployment/waldur-site-agent-openstack -n waldur-agent -- \
  cat /etc/waldur-agent/config.yaml
```

## 📁 Structure du Projet

```
owsa-agent/
├── pyproject.toml                      # Configuration du package Python
├── README.md                           # Ce fichier
├── examples/
│   └── waldur-site-agent-config.yaml   # Exemple de configuration complète
├── kubernetes/
│   ├── deployment.yaml                 # Déploiement K8s/k3s
│   ├── configmap.yaml                  # ConfigMap avec config de l'agent
│   └── secret.yaml                     # Template pour les secrets
└── waldur_site_agent_openstack/
    ├── __init__.py                     # Initialisation du package
    ├── config.py                       # Gestion de backend_settings
    ├── keystone_client.py              # Client Keystone API (À FAIRE)
    ├── backends.py                     # Implémentation BaseBackend (À FAIRE)
    └── utils.py                        # Utilitaires (retry, validation, etc.)
```

## 🤝 Contribution

Les contributions sont les bienvenues !

## 📄 Licence

MIT

## 📞 Support

Pour des questions ou problèmes :
- Issues GitHub : [Créer une issue]
- Documentation Waldur : https://docs.waldur.com
- Documentation waldur-site-agent : https://github.com/waldur/waldur-site-agent

## 🔗 Liens Utiles

- [Waldur](https://waldur.com)
- [waldur-site-agent](https://github.com/waldur/waldur-site-agent)
- [OpenStack Keystone](https://docs.openstack.org/keystone/latest/)
- [python-keystoneclient](https://docs.openstack.org/python-keystoneclient/latest/)
