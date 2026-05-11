# Kubernetes Deployment — Medical Insurance AI Agent

## Prerequisites

- Kubernetes cluster (v1.23+ recommended)
- `kubectl` configured with cluster access
- Ingress controller installed (e.g., NGINX Ingress Controller)
- Metrics Server installed (required for HPA)

## Apply Configurations

Apply all manifests in the following order (or use the directory shortcut):

```bash
# Apply all resources at once
kubectl apply -f deploy/k8s/

# Or apply individually in order
kubectl apply -f deploy/k8s/configmap.yaml
kubectl apply -f deploy/k8s/secret.yaml
kubectl apply -f deploy/k8s/deployment.yaml
kubectl apply -f deploy/k8s/service.yaml
kubectl apply -f deploy/k8s/hpa.yaml
kubectl apply -f deploy/k8s/ingress.yaml
```

## Verify Deployment

```bash
# Check pod status
kubectl get pods -l app=medical-insurance-ai-agent

# Check service
kubectl get svc medical-insurance-ai-agent

# Check HPA
kubectl get hpa medical-insurance-ai-agent

# Check ingress
kubectl get ingress medical-insurance-ai-agent

# View logs
kubectl logs -l app=medical-insurance-ai-agent
```

## Update Secrets

The `secret.yaml` file contains placeholder values encoded in base64. To update with real values:

```bash
# Encode a value (on Linux/macOS)
echo -n "your-actual-api-key" | base64

# On Windows (PowerShell)
[Convert]::ToBase64String([Text.Encoding]::UTF8.GetBytes("your-actual-api-key"))

# Edit secret.yaml with the encoded values, then apply
kubectl apply -f deploy/k8s/secret.yaml

# Restart pods to pick up new secrets (if deployment doesn't auto-rollout)
kubectl rollout restart deployment/medical-insurance-ai-agent
```

## Configuration

Edit `configmap.yaml` to adjust application configuration for your environment:

| Key              | Description                  | Example Value                                          |
|------------------|------------------------------|--------------------------------------------------------|
| `APP_ENV`        | Application environment      | `production`                                           |
| `LOG_LEVEL`      | Logging verbosity            | `info`, `debug`, `warn`, `error`                       |
| `DATABASE_URL`   | PostgreSQL connection string | `postgresql://user:password@host:5432/db?sslmode=disable` |
| `MILVUS_URI`     | Milvus vector DB URI         | `http://milvus:19530`                                  |

## Scaling

The HPA automatically scales the deployment between 2 and 10 replicas based on CPU utilization (target: 70%). To manually scale:

```bash
kubectl scale deployment/medical-insurance-ai-agent --replicas=3
```

## Namespace

All resources are deployed to the **default** namespace. To use a custom namespace:

```bash
kubectl create namespace medical-insurance
kubectl apply -f deploy/k8s/ -n medical-insurance
```

## Clean Up

```bash
kubectl delete -f deploy/k8s/
```
