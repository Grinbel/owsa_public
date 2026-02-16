#!/bin/bash
# ============================================================================
# Script de test du plugin OpenStack pour waldur-site-agent
# ============================================================================
# Usage:
#   1. Remplir test.env avec vos vraies valeurs
#   2. chmod +x test-plugin.sh
#   3. ./test-plugin.sh
# ============================================================================

set -e  # Arrêter en cas d'erreur

# Couleurs pour l'output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

echo -e "${BLUE}============================================================================${NC}"
echo -e "${BLUE}Test du plugin waldur-site-agent-openstack${NC}"
echo -e "${BLUE}============================================================================${NC}"
echo ""

# ============================================================================
# Étape 1 : Vérifier que test.env existe et est rempli
# ============================================================================
echo -e "${YELLOW}[1/7] Vérification de test.env...${NC}"

if [ ! -f "test.env" ]; then
    echo -e "${RED}❌ Fichier test.env introuvable!${NC}"
    echo "Créez le fichier test.env et remplissez-le avec vos credentials."
    exit 1
fi

source test.env

if [ -z "$WALDUR_API_TOKEN" ] || [ "$WALDUR_API_TOKEN" = "VOTRE_TOKEN_ICI" ]; then
    echo -e "${RED}❌ test.env n'est pas rempli correctement!${NC}"
    echo "Éditez test.env et remplacez les valeurs par défaut."
    exit 1
fi

echo -e "${GREEN}✓ test.env chargé${NC}"
echo ""

# ============================================================================
# Étape 2 : Vérifier que le venv existe
# ============================================================================
echo -e "${YELLOW}[2/7] Vérification de l'environnement Python...${NC}"

if [ ! -d ".venv" ]; then
    echo -e "${YELLOW}Création du venv...${NC}"
    uv venv
fi

source .venv/bin/activate

echo -e "${GREEN}✓ venv activé${NC}"
echo ""

# ============================================================================
# Étape 3 : Installer les dépendances
# ============================================================================
echo -e "${YELLOW}[3/7] Installation des dépendances...${NC}"

# Installer le plugin en mode éditable
echo -e "${YELLOW}Installation du plugin OpenStack en mode éditable...${NC}"
uv pip install -e . ".[dev]"

# Installer waldur-site-agent
if ! command -v waldur_site_agent &> /dev/null; then
    echo -e "${YELLOW}Installation de waldur-site-agent depuis GitHub...${NC}"
    uv pip install git+https://github.com/waldur/waldur-site-agent.git@main
else
    echo -e "${GREEN}✓ waldur-site-agent déjà installé (utilisation du cache)${NC}"
fi

echo -e "${GREEN}✓ Dépendances installées${NC}"
echo ""

# ============================================================================
# Étape 4 : Vérifier que le plugin est découvert
# ============================================================================
echo -e "${YELLOW}[4/7] Vérification de la découverte du plugin...${NC}"

BACKENDS=$(python -c "from importlib.metadata import entry_points; print([ep.name for ep in entry_points(group='waldur_site_agent.backends')])")

if [[ $BACKENDS == *"openstack"* ]]; then
    echo -e "${GREEN}✓ Plugin OpenStack découvert: $BACKENDS${NC}"
else
    echo -e "${RED}❌ Plugin OpenStack NON découvert!${NC}"
    echo "Backends disponibles: $BACKENDS"
    exit 1
fi
echo ""

# ============================================================================
# Étape 5 : Tester la connexion Waldur API
# ============================================================================
echo -e "${YELLOW}[5/7] Test de connexion à Waldur API...${NC}"
echo -e "OPENSTACK VERIFY SSL MODE = $OPENSTACK_VERIFY_SSL"

CURL_INSECURE=""
if [ "${OPENSTACK_VERIFY_SSL,,}" = "false" ]; then
    CURL_INSECURE="--insecure"
fi

RESPONSE=$(curl -sS \
    -w "\n---CURL_META---\nhttp_code=%{http_code}\nhttp_version=%{http_version}\ntime_namelookup=%{time_namelookup}s\ntime_connect=%{time_connect}s\ntime_appconnect=%{time_appconnect}s\ntime_starttransfer=%{time_starttransfer}s\ntime_total=%{time_total}s\nremote_ip=%{remote_ip}\nremote_port=%{remote_port}\nscheme=%{scheme}\nssl_verify_result=%{ssl_verify_result}\nsize_download=%{size_download} bytes\nsize_header=%{size_header} bytes\ncontent_type=%{content_type}\nurl_effective=%{url_effective}\nnum_redirects=%{num_redirects}" \
    -H "Authorization: Token ${WALDUR_API_TOKEN}" \
    "${WALDUR_API_URL}/configuration/" \
    $CURL_INSECURE)

RESPONSE_BODY=$(echo "$RESPONSE" | sed '/^---CURL_META---$/,$d') #supp les meta with d
CURL_META=$(echo "$RESPONSE" | sed -n '/^---CURL_META---$/,$p' | tail -n +2) # -n no default print, and p prints only this, tail to start from 2nd line 
HTTP_CODE=$(echo "$CURL_META" | grep '^http_code=' | cut -d= -f2) # cut set delemiter to = then take field 2

echo -e "${BLUE}--- Curl transfer details ---${NC}"
echo "$CURL_META"
echo -e "${BLUE}--- Response body ---${NC}"
echo "$RESPONSE_BODY" | python3 -c "
import sys, json
try:
    data = json.load(sys.stdin) # get input
    print(json.dumps(data, indent=2)) # print json format data input
except json.JSONDecodeError as e: # capture json decoding err
    print(f"parsing error: {e.msg} at line {e.lineno} col {e.colno}")
    #print(sys.stdin.read())
" 2>/dev/null || echo "$RESPONSE_BODY"
echo -e "${BLUE}-----------------------------${NC}"

if [ "$HTTP_CODE" = "200" ]; then
    echo -e "${GREEN}✓ Connexion Waldur API réussie (HTTP $HTTP_CODE)${NC}"
else
    echo -e "${RED}❌ Échec connexion Waldur API (HTTP $HTTP_CODE)${NC}"
    echo "Vérifiez WALDUR_API_URL et WALDUR_API_TOKEN dans test.env"
    exit 1
fi
echo ""

# ============================================================================
# Étape 6 : Tester la connexion OpenStack Keystone
# ============================================================================
echo -e "${YELLOW}[6/7] Test de connexion à OpenStack Keystone...${NC}"

python << EOF
import sys
try:
    from keystoneauth1.identity import v3
    from keystoneauth1 import session

    auth = v3.Password(
        auth_url="${OPENSTACK_AUTH_URL}",
        username="${OPENSTACK_USERNAME}",
        password="${OPENSTACK_PASSWORD}",
        project_name="${OPENSTACK_PROJECT_NAME}",
        user_domain_name="${OPENSTACK_USER_DOMAIN_NAME}",
        project_domain_name="${OPENSTACK_PROJECT_DOMAIN_NAME}"
    )
    sess = session.Session(auth=auth, verify=${OPENSTACK_VERIFY_SSL})
    token = sess.get_token()
    print("✓ Connexion Keystone réussie (token obtenu)")
    sys.exit(0)
except Exception as e:
    print(f"❌ Échec connexion Keystone: {e}")
    sys.exit(1)
EOF

if [ $? -ne 0 ]; then
    echo -e "${RED}Vérifiez les credentials OpenStack dans test.env${NC}"
    exit 1
fi
echo ""

# ============================================================================
# Étape 7 : Exécuter waldur_site_load_components
# ============================================================================
echo -e "${YELLOW}[7/7] Chargement des composants dans Waldur...${NC}"

# Vérifier que envsubst est disponible
if ! command -v envsubst &> /dev/null; then
    echo -e "${RED}❌ envsubst n'est pas disponible!${NC}"
    echo "Installez gettext: sudo apt-get install gettext"
    exit 1
fi

# Substituer les variables d'environnement dans test-config.yaml
echo -e "${YELLOW}Substitution des variables d'environnement...${NC}"
envsubst < test-config.yaml > test-config-final.yaml

if [ $? -ne 0 ]; then
    echo -e "${RED}❌ Erreur lors de la substitution des variables${NC}"
    rm -f test-config-final.yaml
    exit 1
fi

echo -e "${GREEN}✓ Variables d'environnement substituées${NC}"

# Lancer waldur_site_load_components avec le fichier substitué
waldur_site_load_components -c test-config-final.yaml

if [ $? -eq 0 ]; then
    echo -e "${GREEN}✓ Composants chargés avec succès${NC}"
    # Nettoyer le fichier temporaire
else
    echo -e "${RED}❌ Échec du chargement des composants${NC}"
    # Garder le fichier pour déboguer
    echo -e "${BLUE}Fichier de config (avec variables substituées): test-config-final.yaml${NC}"
    rm -f test-config-final.yaml
    exit 1
fi
echo ""

# ============================================================================
# Résumé et prochaines étapes
# ============================================================================
echo -e "${GREEN}============================================================================${NC}"
echo -e "${GREEN}✓ Tous les tests sont passés!${NC}"
echo -e "${GREEN}============================================================================${NC}"
echo ""
echo -e "${BLUE}Prochaines étapes:${NC}"
echo ""
echo -e "  ${YELLOW}1. Tester en mode membership-sync (polling):${NC}"
echo -e "     envsubst < test-config.yaml | waldur-site-agent run --mode membership-sync --config /dev/stdin"
echo -e "     OU pour chaque exécution:"
echo -e "     envsubst < test-config.yaml > test-config-final.yaml"
echo -e "     waldur-site-agent run --mode membership-sync --config test-config-final.yaml"
echo ""
echo -e "  ${YELLOW}2. UPCOMING script vérification des logs pour voir la synchronisation:${NC}"
echo -e "     - Connexion à Waldur"
echo -e "     - Découverte du backend OpenStack"
echo -e "     - Synchronisation des utilisateurs"
echo ""
echo -e "  ${YELLOW}3. Tester en mode event-process (temps réel avec STOMP):${NC}"
echo -e "     a) Exposer RabbitMQ (dans un autre terminal) en portforward ou setup ingress et renseigner stomp values dans config.yaml:${NC}"
echo -e "        kubectl port-forward -n waldur-namespace svc/waldur-release-rabbitmq 61613:61613"
echo -e "     b) Générer le fichier config avec variables substituées: (le script le fait)${NC}"
echo -e "        envsubst < test-config.yaml > test-config-final.yaml"
echo -e "     c) Vérifier que stomp_enabled: true est dans test-config-final.yaml${NC}"
echo -e "     d) Lancer l'agent:${NC}"
echo -e "        waldur_site_agent --mode event_process --config-file test-config-final.yaml"
echo ""
echo -e "  ${YELLOW}4. Dans Waldur UI:${NC}"
echo -e "     - Ajouter un utilisateur à un projet"
echo -e "     - Vérifier qu'il apparaît en temps réel dans OpenStack Keystone"
echo ""
echo -e "${GREEN}Bon test! 🚀${NC}"
