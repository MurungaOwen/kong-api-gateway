local cjson  = require "cjson.safe"
local http   = require "resty.http"
local event  = require "kong.plugins.billing-meter.event"

local BillingMeter = {
  PRIORITY = 10,      -- log phase: order barely matters
  VERSION  = "0.1.0",
}

-- The log phase forbids cosockets, so ship the event from a zero-delay timer.
local function send(premature, url, timeout_ms, payload)
  if premature then return end
  local client = http.new()
  client:set_timeout(timeout_ms)
  local res, err = client:request_uri(url, {
    method  = "POST",
    body    = payload,
    headers = { ["Content-Type"] = "application/json" },
  })
  if not res then
    kong.log.err("billing-meter: ingest unreachable: ", err)
  elseif res.status >= 300 then
    kong.log.err("billing-meter: ingest returned ", res.status)
  end
end

function BillingMeter:log(conf)
  local route   = kong.router.get_route()
  local service = kong.router.get_service()
  local ser = kong.log.serialize()
  local ev = event.build({
    consumer     = kong.client.get_consumer(),
    status       = kong.response.get_status(),
    route_name   = route and route.name,
    service_name = service and service.name,
    units        = conf.units,
    latency_ms   = ser.latencies and ser.latencies.request,
    ts_ms        = ngx.req.start_time() * 1000,
    request_id   = ser.request and ser.request.id,
  })
  if not ev then return end

  local payload = cjson.encode(ev)
  local ok, err = ngx.timer.at(0, send, conf.ingest_url, conf.timeout_ms, payload)
  if not ok then
    kong.log.err("billing-meter: could not schedule send: ", err)
  end
end

return BillingMeter
