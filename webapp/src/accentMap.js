// Mirrors font_tool.py ACCENT_MAP and cli.py _STRIP_MAP.
// Single source of truth for accent/proxy logic in the webapp.
// Update here when the proxy char mapping changes.

export const ACCENT_SUPPORTED = {
  'á': '@', 'é': '#', 'í': '$', 'ó': '&', 'ú': '*', 'ñ': '_', 'ü': '=',
}

export const PROXY_CHARS = new Set(Object.values(ACCENT_SUPPORTED))

export const ACCENT_STRIP = {
  'Á':'A','à':'a','À':'A','â':'a','Â':'A','ä':'a','Ä':'A','ã':'a','Ã':'A','å':'a','Å':'A',
  'É':'E','è':'e','È':'E','ê':'e','Ê':'E','ë':'e','Ë':'E',
  'Í':'I','ì':'i','Ì':'I','î':'i','Î':'I','ï':'i','Ï':'I',
  'Ó':'O','ò':'o','Ò':'O','ô':'o','Ô':'O','ö':'o','Ö':'O','õ':'o','Õ':'O',
  'Ú':'U','ù':'u','Ù':'U','û':'u','Û':'U','Ü':'U',
  'Ñ':'N','ç':'c','Ç':'C','ý':'y','Ý':'Y','ÿ':'y',
}

export const LINE_CHAR_LIMITS = [33, 33, 31]

// Shift-JIS 2-byte symbols the game supports natively (cost 2 bytes each in the binary).
export const SJIS_SYMBOLS = new Set(['○', '×', '□', '→', '←', '↑', '↓'])
