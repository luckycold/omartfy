.pragma library

function parseLine(line) {
  try {
    var value = JSON.parse(String(line || ""))
    return value && typeof value === "object" && !Array.isArray(value) ? value : null
  } catch (error) {
    return null
  }
}

function priorityMeta(priority) {
  var value = Number(priority)
  if (!isFinite(value) || value < 1 || value > 5) value = 3
  if (value === 5) return { value: 5, label: "Urgent", glyph: "󰀦", urgent: true }
  if (value === 4) return { value: 4, label: "High", glyph: "󰁝", urgent: false }
  if (value === 2) return { value: 2, label: "Low", glyph: "󰁅", urgent: false }
  if (value === 1) return { value: 1, label: "Minimum", glyph: "󰂚", urgent: false }
  return { value: 3, label: "Default", glyph: "󰂚", urgent: false }
}

function relativeTime(epochSeconds, nowMs) {
  var epoch = Number(epochSeconds)
  var now = Number(nowMs)
  if (!isFinite(now)) now = Date.now()
  if (!isFinite(epoch) || epoch <= 0) return "now"
  var seconds = Math.max(0, Math.floor(now / 1000 - epoch))
  if (seconds < 60) return "now"
  if (seconds < 3600) return Math.floor(seconds / 60) + "m"
  if (seconds < 86400) return Math.floor(seconds / 3600) + "h"
  if (seconds < 604800) return Math.floor(seconds / 86400) + "d"
  var date = new Date(epoch * 1000)
  return (date.getMonth() + 1) + "/" + date.getDate()
}

function filterRows(rows, serverId, query) {
  var source = Array.isArray(rows) ? rows : []
  var selected = String(serverId || "all")
  var needle = String(query || "").trim().toLowerCase()
  var result = source.filter(function(row) {
    if (!row || typeof row !== "object") return false
    if (selected !== "all" && String(row.serverId || "") !== selected) return false
    if (!needle) return true
    var tags = Array.isArray(row.tags) ? row.tags.join(" ") : ""
    var haystack = [row.serverLabel, row.topic, row.title, row.message, tags]
      .map(function(value) { return String(value || "").toLowerCase() }).join("\n")
    return haystack.indexOf(needle) >= 0
  })
  result.sort(function(a, b) {
    var byTime = Number(b.time || 0) - Number(a.time || 0)
    if (byTime !== 0) return byTime
    return String(b.id || "").localeCompare(String(a.id || ""))
  })
  return result
}

function tabLayout(servers, selectedServerId, maxNamedTabs) {
  var source = Array.isArray(servers) ? servers.slice() : []
  var limit = Math.max(0, Number(maxNamedTabs) || 0)
  var selected = String(selectedServerId || "all")
  var named = source.slice(0, limit)
  var selectedIndex = source.findIndex(function(server) {
    return String(server.id || "") === selected
  })
  if (selectedIndex >= limit && limit > 0) named[limit - 1] = source[selectedIndex]
  var namedIds = named.map(function(server) { return String(server.id || "") })
  var more = source.filter(function(server) {
    return namedIds.indexOf(String(server.id || "")) < 0
  })
  return {
    tabs: [{ id: "all", label: "All" }].concat(named),
    named: named,
    more: more
  }
}

function serverSummary(servers, unreadCount) {
  var source = Array.isArray(servers) ? servers : []
  var enabled = source.filter(function(server) { return server.enabled !== false })
  var connected = enabled.filter(function(server) { return server.state === "connected" }).length
  var unread = Math.max(0, Number(unreadCount) || 0)
  if (source.length === 0) return "Add a server to begin"
  return unread + " unread · " + connected + "/" + enabled.length + " servers connected"
}

function actionDisplay(action) {
  if (!action || typeof action !== "object") return ""
  var type = String(action.action || "")
  if (type === "http") {
    var method = String(action.method || "POST").toUpperCase()
    try {
      var parsed = new URL(String(action.url || ""))
      return method + " " + parsed.host
    } catch (error) {
      return method + " invalid destination"
    }
  }
  if (type === "copy") return "Copy"
  if (type === "view") return "Open"
  return ""
}
