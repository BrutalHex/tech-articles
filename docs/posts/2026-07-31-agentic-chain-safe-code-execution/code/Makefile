.DEFAULT_GOAL := help

.PHONY: help tools \
	install-curl install-kind install-kubectl install-kustomize install-gvisor \
	setup-kind delete-kind \
	docker-config docker-build docker-test docker-push load-kind \
	kustomize-build secret apply deploy wait-ready verify-isolation \
	clean-all undeploy logs test

# Versions (latest as of 2026-08-02)
VERSION ?= v2026.08.01
KIND_VERSION ?= v0.32.0
KUBECTL_VERSION ?= v1.36.3
KUSTOMIZE_VERSION ?= v5.8.1
AGENT_SANDBOX_VERSION ?= v0.5.4
# Static curl from https://github.com/stunnel/static-curl/releases
CURL_VERSION ?= 8.21.0
# gVisor release channel for host binaries mounted into kind nodes.
GVISOR_RELEASE ?= latest

# Image
IMAGE_NAME ?= agentic-chain-ui
IMAGE_TAG ?= $(VERSION)
# Local image name used by kind load / deployment.
IMAGE ?= $(IMAGE_NAME):$(IMAGE_TAG)
# Optional registry prefix for docker-push, e.g. docker.io/myuser or ghcr.io/org
REGISTRY ?=
FULL_IMAGE ?= $(if $(REGISTRY),$(REGISTRY)/$(IMAGE),$(IMAGE))

# Paths
OS_RAW := $(shell uname -s | tr '[:upper:]' '[:lower:]')
ARCH_RAW := $(shell uname -m)
OS := ${OS_RAW}
ARCH := ${ARCH_RAW}

KUSTOMIZE_DIR := ./kustomize
SRC_DIR := ./src
BIN_DIR := ./bin

ifeq (${ARCH_RAW},x86_64)
	ARCH := amd64
	GVISOR_ARCH := x86_64
	# stunnel/static-curl asset arch (linux musl uses x86_64; macOS uses x86_64)
	CURL_ARCH := x86_64
endif
ifeq (${ARCH_RAW},aarch64)
	ARCH := arm64
	GVISOR_ARCH := aarch64
	# Linux musl assets use aarch64; macOS assets use arm64 (set below for darwin).
	CURL_ARCH := aarch64
endif
ifeq (${ARCH_RAW},arm64)
	ARCH := arm64
	GVISOR_ARCH := aarch64
	CURL_ARCH := arm64
endif
# Default if uname is unusual.
GVISOR_ARCH ?= x86_64
CURL_ARCH ?= x86_64
# macOS arm64 (Apple Silicon reports arm64; ensure curl asset name matches).
ifeq ($(OS),darwin)
ifeq ($(ARCH_RAW),aarch64)
	CURL_ARCH := arm64
endif
endif

export PATH := $(CURDIR)/$(BIN_DIR):$(PATH)

CURL := $(BIN_DIR)/curl
KIND := $(BIN_DIR)/kind
KUBECTL := $(BIN_DIR)/kubectl
KUSTOMIZE := $(BIN_DIR)/kustomize

help: ## Show this help
	@awk 'BEGIN {FS = ":.*##"; printf "\nUsage:\n  make \033[36m<target>\033[0m\n"} /^[a-zA-Z_0-9-]+:.*?##/ { printf "  \033[36m%-22s\033[0m %s\n", $$1, $$2 } /^##@/ { printf "\n\033[1m%s\033[0m\n", substr($$0, 5) } ' $(MAKEFILE_LIST)

##@ Tooling
tools: install-curl install-kind install-kubectl install-kustomize install-gvisor ## Install curl, kind, kubectl, kustomize, gVisor into ./bin

install-curl: ## Install static curl into ./bin if missing (linux/darwin)
	@mkdir -p $(BIN_DIR)
	@if [ ! -x $(CURL) ]; then \
		echo "Installing curl $(CURL_VERSION) for ${OS}/$(CURL_ARCH)..."; \
		case "${OS}" in \
		  linux) asset="curl-linux-$(CURL_ARCH)-musl-$(CURL_VERSION).tar.xz" ;; \
		  darwin) asset="curl-macos-$(CURL_ARCH)-$(CURL_VERSION).tar.xz" ;; \
		  *) echo "Unsupported OS: ${OS}"; exit 1 ;; \
		esac; \
		url="https://github.com/stunnel/static-curl/releases/download/$(CURL_VERSION)/$$asset"; \
		tmp=$$(mktemp -d); \
		if command -v curl >/dev/null 2>&1; then curl -fsSL -o "$$tmp/curl.tar.xz" "$$url"; \
		elif command -v wget >/dev/null 2>&1; then wget -qO "$$tmp/curl.tar.xz" "$$url"; \
		else echo "Need system curl or wget once to bootstrap ./bin/curl"; rm -rf "$$tmp"; exit 1; fi; \
		tar -xJf "$$tmp/curl.tar.xz" -C "$$tmp" curl; \
		mv "$$tmp/curl" $(CURL); \
		chmod +x $(CURL); \
		rm -rf "$$tmp"; \
	fi
	@$(CURL) --version | head -n 1

install-kind: install-curl ## Install KIND into ./bin if missing
	@mkdir -p $(BIN_DIR)
	@if [ ! -x $(KIND) ]; then \
		echo "Installing KIND $(KIND_VERSION) for ${OS}/${ARCH}..."; \
		case "${OS}" in \
		  darwin|linux) $(CURL) -fsSL -o $(KIND) https://kind.sigs.k8s.io/dl/$(KIND_VERSION)/kind-${OS}-${ARCH} ;; \
		  *) echo "Unsupported OS: ${OS}"; exit 1 ;; \
		esac; \
		chmod +x $(KIND); \
	fi
	@$(KIND) --version

install-kubectl: install-curl ## Install kubectl into ./bin if missing
	@mkdir -p $(BIN_DIR)
	@if [ ! -x $(KUBECTL) ]; then \
		echo "Installing kubectl $(KUBECTL_VERSION) for ${OS}/${ARCH}..."; \
		case "${OS}" in \
		  darwin|linux) $(CURL) -fsSL -o $(KUBECTL) "https://dl.k8s.io/release/$(KUBECTL_VERSION)/bin/${OS}/${ARCH}/kubectl" ;; \
		  *) echo "Unsupported OS: ${OS}"; exit 1 ;; \
		esac; \
		chmod +x $(KUBECTL); \
	fi
	@$(KUBECTL) version --client

install-kustomize: install-curl ## Install kustomize into ./bin if missing
	@mkdir -p $(BIN_DIR)
	@if [ ! -x $(KUSTOMIZE) ]; then \
		echo "Installing kustomize $(KUSTOMIZE_VERSION) for ${OS}/${ARCH}..."; \
		$(CURL) -fsSL "https://github.com/kubernetes-sigs/kustomize/releases/download/kustomize%2F$(KUSTOMIZE_VERSION)/kustomize_$(KUSTOMIZE_VERSION)_${OS}_${ARCH}.tar.gz" \
		  | tar -xz -C $(BIN_DIR) kustomize; \
		chmod +x $(KUSTOMIZE); \
	fi
	@$(KUSTOMIZE) version

install-gvisor: install-curl ## Install gVisor runsc + containerd shim into ./bin (mounted into kind)
	@mkdir -p $(BIN_DIR)
	@if [ ! -x $(BIN_DIR)/runsc ] || [ ! -x $(BIN_DIR)/containerd-shim-runsc-v1 ]; then \
		echo "Installing gVisor ($(GVISOR_RELEASE)) for $(GVISOR_ARCH)..."; \
		url="https://storage.googleapis.com/gvisor/releases/release/$(GVISOR_RELEASE)/$(GVISOR_ARCH)"; \
		$(CURL) -fsSL -o $(BIN_DIR)/runsc "$$url/runsc"; \
		$(CURL) -fsSL -o $(BIN_DIR)/containerd-shim-runsc-v1 "$$url/containerd-shim-runsc-v1"; \
		chmod a+rx $(BIN_DIR)/runsc $(BIN_DIR)/containerd-shim-runsc-v1; \
	fi
	@$(BIN_DIR)/runsc --version 2>/dev/null || $(BIN_DIR)/runsc -version 2>/dev/null || echo "runsc installed at $(BIN_DIR)/runsc"

##@ Kind cluster
KIND_CONFIG_TPL := $(KUSTOMIZE_DIR)/kind-config.yaml.tpl
KIND_CONFIG := $(KUSTOMIZE_DIR)/kind-config.generated.yaml

$(KIND_CONFIG): $(KIND_CONFIG_TPL) install-gvisor
	@# Absolute host paths required for kind extraMounts of runsc binaries.
	@sed "s|__BIN_DIR__|$(CURDIR)/$(BIN_DIR)|g" $(KIND_CONFIG_TPL) > $(KIND_CONFIG)
	@echo "Wrote $(KIND_CONFIG) with gVisor mounts from $(CURDIR)/$(BIN_DIR)"

setup-kind: tools $(KIND_CONFIG) ## Create (or reuse) a KIND cluster with gVisor runtime
	@echo "Setting up KIND cluster (config=$(KIND_CONFIG), gVisor enabled)"
	@NODE_IMAGE=$${NODE_IMAGE:-kindest/node:v1.34.0}; \
	if $(KIND) get clusters 2>/dev/null | grep -q '^kind$$'; then \
		 echo "KIND cluster already exists; reusing (delete-kind first to pick up gVisor mounts)."; \
	else \
		$(KIND) create cluster --image $$NODE_IMAGE --config $(KIND_CONFIG); \
	fi; \
	echo "Waiting for KIND cluster to be ready..."; \
	$(KUBECTL) wait --for=condition=Ready nodes --all --timeout=300s; \
	# local-path lives in local-path-storage (not kube-system) on kind.
	-$(KUBECTL) -n kube-system scale deploy/coredns --replicas=1; \
	-$(KUBECTL) -n local-path-storage scale deploy/local-path-provisioner --replicas=0 2>/dev/null || true; \
	-$(KUBECTL) -n kube-system scale deploy/local-path-provisioner --replicas=0 2>/dev/null || true; \
	# Ensure runsc is executable inside the node (bind-mount can drop +x on some hosts).
	-docker exec kind-control-plane chmod a+rx /usr/local/bin/runsc /usr/local/bin/containerd-shim-runsc-v1 2>/dev/null || true; \
	-docker exec kind-control-plane runsc --version 2>/dev/null || docker exec kind-control-plane runsc -version 2>/dev/null || true

delete-kind: tools ## Delete KIND cluster (CLUSTER_NAME=kind)
	@CLUSTER_NAME=$${CLUSTER_NAME:-kind}; \
	if $(KIND) get clusters 2>/dev/null | grep -q "^$$CLUSTER_NAME$$"; then \
		$(KIND) delete cluster --name $$CLUSTER_NAME; \
		echo "Cluster '$$CLUSTER_NAME' deleted."; \
	else \
		echo "Cluster '$$CLUSTER_NAME' not found; nothing to delete."; \
	fi

##@ Docker image
DOCKER_CONFIG_DIR := $(CURDIR)/.docker-build
export DOCKER_CONFIG := $(DOCKER_CONFIG_DIR)
# Single-platform, no attestations — kind load fails on multi-arch index digests.
DOCKER_BUILD_FLAGS ?= --platform=linux/amd64 --provenance=false --sbom=false
# Build inside a Docker CLI container so host Docker config quirks stay out of band.
DOCKER_BUILD_CONTAINER ?= docker:27-cli

docker-config: ## Prepare a credential-store-free Docker config for reliable builds
	@mkdir -p $(DOCKER_CONFIG_DIR)
	@printf '%s\n' '{' '  "auths": {}' '}' > $(DOCKER_CONFIG_DIR)/config.json

docker-build: docker-config ## Build the Chainlit app image in a container (tag=$(IMAGE))
	@echo "Building $(IMAGE) from $(SRC_DIR) via $(DOCKER_BUILD_CONTAINER)"
	@# Mount source + docker.sock; run docker CLI in a container.
	@# Writable /root/.docker so buildx can write activity metadata.
	docker run --rm \
		-v /var/run/docker.sock:/var/run/docker.sock \
		-v "$(CURDIR)/$(SRC_DIR):/src:ro" \
		-v "$(DOCKER_CONFIG_DIR):/root/.docker" \
		-e DOCKER_CONFIG=/root/.docker \
		-w /src \
		$(DOCKER_BUILD_CONTAINER) \
		docker build $(DOCKER_BUILD_FLAGS) -t $(IMAGE) .
	@if [ -n "$(REGISTRY)" ]; then \
		docker tag $(IMAGE) $(FULL_IMAGE); \
		echo "Also tagged $(FULL_IMAGE)"; \
	fi

docker-test: docker-build ## Smoke-test the image before push/load
	@echo "Smoke-testing $(IMAGE)..."
	@docker run --rm $(IMAGE) python -c "import chainlit, tools, graph, seed_chroma; from tools import TOOL_REGISTRY; print('imports-ok', sorted(TOOL_REGISTRY))"
	@docker run --rm $(IMAGE) chainlit --help >/dev/null
	@docker run --rm --entrypoint python $(IMAGE) -c "from tools.code_interpreter import ensure_stdout_visibility; s=ensure_stdout_visibility('2+2'); assert 'print' in s; print('stdout-prep-ok')"
	@echo "Image smoke tests passed."

docker-push: docker-test ## Push image to REGISTRY (required) after smoke tests
	@if [ -z "$(REGISTRY)" ]; then \
		echo "ERROR: REGISTRY is required for docker-push (e.g. make docker-push REGISTRY=docker.io/myuser)"; \
		exit 1; \
	fi
	@echo "Pushing $(FULL_IMAGE)"
	docker tag $(IMAGE) $(FULL_IMAGE)
	docker push $(FULL_IMAGE)

load-kind: docker-test setup-kind ## Build, test, and load app + runtime images into KIND
	@echo "Loading images into kind (serial, low-memory; direct then flatten)"
	@for img in \
		"$(IMAGE)" \
		"registry.k8s.io/agent-sandbox/python-runtime-sandbox:$(AGENT_SANDBOX_VERSION)" \
		"registry.k8s.io/agent-sandbox/agent-sandbox-controller:$(AGENT_SANDBOX_VERSION)" \
		"postgres:16-alpine"; do \
		echo "=== Loading $$img ==="; \
		if $(KIND) load docker-image "$$img"; then \
			echo "Direct load ok: $$img"; \
		else \
			echo "Direct load failed; flattening $$img to single-platform..."; \
			flat="kind-flat-$$(echo "$$img" | tr '/:' '--')"; \
			tmp=$$(mktemp -d); \
			printf 'FROM %s\n' "$$img" > "$$tmp/Dockerfile"; \
			docker build $(DOCKER_BUILD_FLAGS) -t "$$flat" "$$tmp"; \
			rm -rf "$$tmp"; \
			$(KIND) load docker-image "$$flat"; \
			docker exec kind-control-plane ctr -n k8s.io images tag \
				"docker.io/library/$$flat:latest" "$$img" >/dev/null 2>&1 || true; \
			case "$$img" in \
				*/*) ;; \
				*) docker exec kind-control-plane ctr -n k8s.io images tag \
					"docker.io/library/$$flat:latest" "docker.io/library/$$img" >/dev/null 2>&1 || true ;; \
			esac; \
			echo "Flattened load ok: $$img"; \
		fi; \
		sleep 2; \
	done
	@echo "All images loaded."

##@ Kubernetes (kustomize)
kustomize-build: tools ## Render manifests to stdout
	$(KUSTOMIZE) build $(KUSTOMIZE_DIR)

secret: tools ## Create/update agentic-chain-secrets from ./.env
	@if [ ! -f ./.env ]; then echo "Missing ./.env"; exit 1; fi
	@$(KUBECTL) get ns agentic-chain >/dev/null 2>&1 || $(KUBECTL) create ns agentic-chain
	@# Strip comments/blank lines (POSIX; no bash process-substitution)
	@tmp=$$(mktemp); \
	grep -E '^[A-Za-z_][A-Za-z0-9_]*=' ./.env | sed 's/^[ ]*//;s/[ ]*$$//' > "$$tmp"; \
	$(KUBECTL) create secret generic agentic-chain-secrets \
		--namespace agentic-chain \
		--from-env-file="$$tmp" \
		--dry-run=client -o yaml | $(KUBECTL) apply -f -; \
	rm -f "$$tmp"
	@echo "Secret agentic-chain-secrets applied in agentic-chain"

apply: tools ## Apply full kustomize stack (kubectl -k)
	@echo "Applying agent-sandbox operator $(AGENT_SANDBOX_VERSION) (CRDs + controller)"
	$(KUBECTL) apply --server-side -k $(KUSTOMIZE_DIR)/agent-sandbox-operator
	@echo "Waiting for agent-sandbox CRDs to establish..."
	@$(KUBECTL) wait --for=condition=Established \
		crd/sandboxes.agents.x-k8s.io \
		crd/sandboxtemplates.extensions.agents.x-k8s.io \
		crd/sandboxwarmpools.extensions.agents.x-k8s.io \
		crd/sandboxclaims.extensions.agents.x-k8s.io \
		--timeout=120s
	@echo "Waiting for agent-sandbox controller..."
	@$(KUBECTL) -n agent-sandbox-system wait --for=condition=Available deploy/agent-sandbox-controller --timeout=300s || true
	@$(MAKE) secret
	@echo "Applying full stack $(VERSION) via kubectl -k $(KUSTOMIZE_DIR)"
	$(KUBECTL) apply --server-side -k $(KUSTOMIZE_DIR)
	@echo "Apply complete."

deploy: load-kind apply wait-ready ## Full POC path: kind + image + apply + wait
	@echo "Deploy complete. Chainlit UI: http://127.0.0.1:30080 (NodePort; needs kind extraPortMappings)"

wait-ready: tools ## Wait for core workloads to become ready
	@echo "Waiting for agent-sandbox controller..."
	@$(KUBECTL) -n agent-sandbox-system wait --for=condition=Available deploy --all --timeout=300s || true
	@echo "Waiting for postgres/chroma/app..."
	@$(KUBECTL) -n agentic-chain wait --for=condition=Available deploy/postgres deploy/chroma --timeout=300s
	@$(KUBECTL) -n agentic-chain wait --for=condition=Available deploy/agentic-chain-app --timeout=600s || \
		($(KUBECTL) -n agentic-chain describe deploy/agentic-chain-app; \
		 $(KUBECTL) -n agentic-chain get pods -o wide; \
		 $(KUBECTL) -n agentic-chain logs deploy/agentic-chain-app --all-containers --tail=80 || true; \
		 exit 1)
	@echo "Waiting for warm pool sandboxes..."
	@$(KUBECTL) -n agentic-chain get sandboxwarmpool python-sandbox-warmpool || true
	@$(KUBECTL) -n agentic-chain get sandboxes || true
	@$(MAKE) verify-isolation

verify-isolation: tools ## Confirm RuntimeClass/gvisor and sandbox pods use it
	@echo "=== RuntimeClasses ==="
	@$(KUBECTL) get runtimeclass gvisor kata -o wide 2>/dev/null || $(KUBECTL) get runtimeclass
	@echo "=== SandboxTemplate runtimeClassName ==="
	@$(KUBECTL) -n agentic-chain get sandboxtemplate python-runtime-template \
		-o jsonpath='{.spec.podTemplate.spec.runtimeClassName}{"\n"}' 2>/dev/null || true
	@echo "=== Sandbox pods runtimeClassName ==="
	@pods=$$($(KUBECTL) -n agentic-chain get pods -l app=python-runtime-sandbox -o name 2>/dev/null); \
	if [ -z "$$pods" ]; then echo "(no sandbox pods yet)"; exit 0; fi; \
	ok=0; \
	for p in $$pods; do \
		rc=$$($(KUBECTL) -n agentic-chain get $$p -o jsonpath='{.spec.runtimeClassName}'); \
		phase=$$($(KUBECTL) -n agentic-chain get $$p -o jsonpath='{.status.phase}'); \
		echo "$$p runtimeClassName=$$rc phase=$$phase"; \
		if [ "$$rc" = "gvisor" ]; then ok=1; fi; \
	done; \
	if [ "$$ok" != "1" ]; then \
		echo "ERROR: expected at least one sandbox pod with runtimeClassName=gvisor"; \
		$(KUBECTL) -n agentic-chain get pods -l app=python-runtime-sandbox -o yaml | head -80; \
		exit 1; \
	fi; \
	echo "gVisor isolation OK."

clean-all: delete-kind ## Delete kind cluster and generated kind config
	@rm -f $(KIND_CONFIG)
	@echo "Clean complete."

undeploy: tools ## Delete the app stack namespace (keeps kind + operator CRDs)
	-$(KUBECTL) delete -k $(KUSTOMIZE_DIR)/stack --wait=false
	@echo "Stack delete requested."

logs: tools ## Tail app logs
	$(KUBECTL) -n agentic-chain logs deploy/agentic-chain-app -c app -f

##@ Local tests
# Prefer project venv when present; fall back to python3 on PATH.
PYTHON ?= $(shell \
	if [ -x "$(CURDIR)/$(SRC_DIR)/.venv/bin/python3" ]; then echo "$(CURDIR)/$(SRC_DIR)/.venv/bin/python3"; \
	elif command -v python3 >/dev/null 2>&1; then command -v python3; \
	else command -v python; fi)

test: ## Run unit tests (sandbox client mocked; no live cluster required)
	@cd $(SRC_DIR) && "$(PYTHON)" -m pytest -q
