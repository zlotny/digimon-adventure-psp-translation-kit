const BASE = '/api'

export async function getFiles() {
  const r = await fetch(`${BASE}/files`)
  if (!r.ok) throw new Error('Failed to load file list')
  return r.json()
}

export async function getFile(category, name) {
  const r = await fetch(`${BASE}/file/${category}/${name}`)
  if (!r.ok) throw new Error(`Failed to load ${category}/${name}`)
  return r.json()
}

export async function saveTranslation(category, name, index, translation) {
  const r = await fetch(`${BASE}/file/${category}/${name}/${index}`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ translation }),
  })
  if (!r.ok) throw new Error('Save failed')
}
