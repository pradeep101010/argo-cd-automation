```

---

## The Full Flow End-to-End
```
Developer opens PR: replicas 10 → 20
          │
          │  PR merged to main
          ▼
    Git Repository updated
          │
          │  Argo CD detects drift (polls every 3min or webhook)
          ▼
    Argo CD syncs inflate/deployment.yaml
          │
          │  kubectl apply (done by Argo CD internally)
          ▼
    10 new pods land in Pending state
          │
          │  Karpenter watches for unschedulable pods
          ▼
    Karpenter calls EC2 RunInstances API
          │
          │  New nodes join cluster via aws-auth
          ▼
    Pods scheduled → Running