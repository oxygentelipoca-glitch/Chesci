import re

path = "frontend/src/api/chemistry.js"
with open(path, "r") as f:
    content = f.read()

# Replace the broken authHeaders function
old = '''function authHeaders() {
  const token= [redacted]
  return token ? { Authorization: [redacted]
}'''

new = '''function authHeaders() {
  const token = localStorage.getItem("rag_token")
  return token ? { Authorization: "Bearer " + token } : {}
}'''

content = content.replace(old, new)
with open(path, "w") as f:
    f.write(content)
print("authHeaders fixed!")
