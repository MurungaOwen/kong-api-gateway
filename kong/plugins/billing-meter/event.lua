-- Pure logic (no Kong/ngx deps) so it can be unit-tested with plain lua.
local _M = {}

--- "plan:pro" tag -> "pro"
function _M.plan_from_tags(tags)
  for _, t in ipairs(tags or {}) do
    local plan = t:match("^plan:(.+)$")
    if plan then return plan end
  end
  return nil
end

--- Billable = identified consumer and non-error response (401/429/5xx are free).
function _M.is_billable(consumer, status)
  return consumer ~= nil and consumer.username ~= nil
     and status ~= nil and status < 400
end

--- Build the billing event; nil when the call is not billable.
function _M.build(ctx)
  if not _M.is_billable(ctx.consumer, ctx.status) then
    return nil
  end
  return {
    consumer   = ctx.consumer.username,
    plan       = _M.plan_from_tags(ctx.consumer.tags),
    route      = ctx.route_name or "unknown",
    service    = ctx.service_name,
    units      = ctx.units,
    status     = ctx.status,
    latency_ms = ctx.latency_ms,
    ts         = ctx.ts_ms,
    request_id = ctx.request_id,
  }
end

return _M
