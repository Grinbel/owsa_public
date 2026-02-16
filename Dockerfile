# ============================================================================
# Dockerfile: waldur-site-agent + plugin OpenStack
# ============================================================================
# Cette image contient UN SEUL processus Python qui exécute waldur-site-agent.
# Le plugin OpenStack est découvert automatiquement via entry-points.
#
# Architecture:
#   Docker image
#   └── Python process: waldur-site-agent
#       ├── Core agent (pip install waldur-site-agent)
#       └── Plugin OpenStack (pip install .) ← Découvert via entry-points
#
# Usage:
#   docker build -t waldur-site-agent-openstack:0.1.0 .
#   docker run -v ./config.yaml:/etc/waldur-agent/config.yaml \
#              waldur-site-agent-openstack:0.1.0
# ============================================================================

FROM python:3.11-slim

LABEL maintainer="ahcene@example.com"
LABEL description="Waldur Site Agent with OpenStack Keystone plugin"

# Variables d'environnement
ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Créer utilisateur non-root
RUN groupadd -r waldur && useradd -r -g waldur -u 1000 waldur

# Installer dépendances système minimales
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    ca-certificates \
    && rm -rf /var/lib/apt/lists/*

# Créer répertoires
RUN mkdir -p /etc/waldur-agent /var/log/waldur-agent /app \
    && chown -R waldur:waldur /etc/waldur-agent /var/log/waldur-agent /app

# Basculer vers utilisateur non-root
USER waldur
WORKDIR /app

# ============================================================================
# ÉTAPE 1 : Installer waldur-site-agent (le daemon principal)
# ============================================================================
# Depuis git (version développement - recommandé pour avoir les dernières features)
RUN pip install --user git+https://github.com/waldur/waldur-site-agent.git@main

# Alternative : Depuis PyPI (si vous voulez une version stable)
# RUN pip install --user waldur-site-agent>=0.7.0

# ============================================================================
# ÉTAPE 2 : Installer le plugin OpenStack
# ============================================================================
# Copier TOUT le code du plugin
COPY --chown=waldur:waldur . /app/waldur-site-agent-openstack/

# Installer le plugin (en mode normal, pas -e car c'est une image)
RUN pip install --user /app/waldur-site-agent-openstack/

# ============================================================================
# ÉTAPE 3 : Vérifier que le plugin est découvert
# ============================================================================
RUN python -c "\
from importlib.metadata import entry_points; \
eps = list(entry_points(group='waldur_site_agent.backends')); \
print('=== Backends découverts ==='); \
[print(f'  ✓ {ep.name}: {ep.value}') for ep in eps]; \
assert any(ep.name == 'openstack' for ep in eps), '❌ Plugin OpenStack NON découvert!'; \
print('✓ Plugin OpenStack découvert avec succès!')"

# ============================================================================
# CONFIGURATION
# ============================================================================
# Le fichier de config sera monté via ConfigMap dans Kubernetes
VOLUME ["/etc/waldur-agent"]

# ============================================================================
# POINT D'ENTRÉE
# ============================================================================
# Lancer waldur-site-agent (qui chargera automatiquement le plugin)
# La commande complète sera : waldur-site-agent run --mode event-process --config /etc/waldur-agent/config.yaml

# Ajouter le PATH de l'utilisateur
ENV PATH="/home/waldur/.local/bin:${PATH}"

# Point d'entrée
ENTRYPOINT ["waldur-site-agent"]

# Arguments par défaut (peuvent être overridés dans k8s)
CMD ["run", "--mode", "event-process", "--config", "/etc/waldur-agent/config.yaml"]

# ============================================================================
# NOTES
# ============================================================================
# - UN SEUL processus tourne : waldur-site-agent
# - Le plugin OpenStack est chargé automatiquement via entry-points
# - Le mode peut être changé via CMD dans deployment.yaml
# - Modes disponibles: event-process, membership-sync, order-process, report
# ============================================================================
