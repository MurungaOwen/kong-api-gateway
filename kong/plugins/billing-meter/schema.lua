local typedefs = require "kong.db.schema.typedefs"

return {
  name = "billing-meter",
  fields = {
    { protocols = typedefs.protocols_http },
    { config = {
        type = "record",
        fields = {
          { ingest_url = typedefs.url { required = true } },
          -- Billing weight of one call on this route (e.g. 5 for an expensive endpoint).
          { units      = { type = "integer", default = 1, between = { 1, 1000000 } } },
          { timeout_ms = { type = "integer", default = 2000 } },
        },
    } },
  },
}
