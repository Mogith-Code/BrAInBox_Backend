"""Admin-only business logic.

Most admin routes should call the service of the module that owns the data
(e.g. `api.modules.questions.service.approve_question`). Put code here only when it
is truly admin-specific, e.g. writing the `audit_log`.
"""

# TODO(Mogith): record_audit(session, actor, action, target_type, target_id, details)
#   -> called by every admin route that changes data.
