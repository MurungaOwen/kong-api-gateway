-- Run: lua5.1 kong/plugins/billing-meter/spec/event_spec.lua
local event = dofile("kong/plugins/billing-meter/event.lua")

local function eq(a, b, msg) assert(a == b, (msg or "") .. ": expected " .. tostring(b) .. " got " .. tostring(a)) end

eq(event.plan_from_tags({ "x", "plan:pro" }), "pro", "plan tag")
eq(event.plan_from_tags({}), nil, "no plan tag")
eq(event.build({ status = 200 }), nil, "anonymous is free")
eq(event.build({ consumer = { username = "a" }, status = 429 }), nil, "429 is free")
eq(event.build({ consumer = { username = "a" }, status = 502 }), nil, "5xx is free")

local ev = event.build({
  consumer = { username = "acme", tags = { "plan:pro" } },
  status = 200, route_name = "r", units = 5, ts_ms = 1, request_id = "id",
})
eq(ev.consumer, "acme", "consumer"); eq(ev.plan, "pro", "plan")
eq(ev.units, 5, "units"); eq(ev.route, "r", "route")
print("event_spec ok")
