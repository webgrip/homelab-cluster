locals {
  labels = {
    "app.kubernetes.io/name"            = "access-plane"
    "access-plane.webgrip.io/managed"   = "true"
    "access-plane.webgrip.io/principal" = "human"
  }
}

resource "kubernetes_cluster_role_binding_v1" "human" {
  for_each = module.model.cluster_bindings

  metadata {
    name   = "human-${each.key}"
    labels = local.labels
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = each.key
  }

  dynamic "subject" {
    for_each = toset(each.value)
    content {
      api_group = "rbac.authorization.k8s.io"
      kind      = "User"
      name      = "oidc:${subject.value}"
    }
  }
}

resource "kubernetes_role_binding_v1" "human" {
  for_each = module.model.namespace_bindings

  metadata {
    name      = "human-${each.value.role}"
    namespace = each.value.namespace
    labels    = local.labels
  }

  role_ref {
    api_group = "rbac.authorization.k8s.io"
    kind      = "ClusterRole"
    name      = each.value.role
  }

  dynamic "subject" {
    for_each = toset(each.value.members)
    content {
      api_group = "rbac.authorization.k8s.io"
      kind      = "User"
      name      = "oidc:${subject.value}"
    }
  }
}
