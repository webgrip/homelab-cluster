locals {
  identity_events = {
    break-glass-login = {
      name       = "Break-glass password login"
      severity   = "alert"
      expression = <<-EOT
        event = request.context.get("event")
        return event is not None and event.action == "login" and event.context.get("auth_method") == "password"
      EOT
    }
    user-created = {
      name       = "User created outside the roster"
      severity   = "warning"
      expression = <<-EOT
        event = request.context.get("event")
        if event is None or event.action != "model_created":
            return False
        return event.context.get("model", {}).get("model_name") == "user"
      EOT
    }
  }
}

resource "authentik_property_mapping_notification" "ntfy_body" {
  name       = "ntfy body"
  expression = <<-EOT
    event = notification.event
    user = (event.user or {}).get("username", "unknown")
    return {
        "topic": "alerts-critical" if notification.severity == "alert" else "alerts-warning",
        "title": f"authentik: {event.action} by {user}",
        "message": notification.body,
        "priority": 5 if notification.severity == "alert" else 4,
        "tags": ["key"],
    }
  EOT
}

resource "authentik_property_mapping_notification" "ntfy_headers" {
  name       = "ntfy headers"
  expression = "return {\"Authorization\": \"Bearer ${data.vault_kv_secret_v2.ntfy.data["alertmanager_token"]}\"}"
}

resource "authentik_event_transport" "ntfy" {
  name                    = "ntfy"
  mode                    = "webhook"
  webhook_url             = "http://ntfy.observability.svc.cluster.local:8080/"
  webhook_mapping_body    = authentik_property_mapping_notification.ntfy_body.id
  webhook_mapping_headers = authentik_property_mapping_notification.ntfy_headers.id
  send_once               = true
}

resource "authentik_policy_expression" "identity_event" {
  for_each = local.identity_events

  name       = "event-${each.key}"
  expression = each.value.expression
}

resource "authentik_event_rule" "identity" {
  for_each = local.identity_events

  name              = each.value.name
  severity          = each.value.severity
  transports        = [authentik_event_transport.ntfy.id]
  destination_group = authentik_group.group["homelab-admins"].id
}

resource "authentik_policy_binding" "identity_event" {
  for_each = local.identity_events

  target  = authentik_event_rule.identity[each.key].id
  policy  = authentik_policy_expression.identity_event[each.key].id
  order   = 0
  enabled = true
}
