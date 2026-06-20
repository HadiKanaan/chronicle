// Day 10 art direction — the single source of UI tokens so every overlay plate,
// button, and canvas accent reads as one cohesive AA pixel-art game instead of a
// pile of one-off styles. JS-side palette/fonts (consumed by both inline React
// styles and the canvas-drawn Minimap); the matching CSS frame, fonts, and
// motion live in theme.css. Dark medieval-fantasy: deep slate ground, aged
// parchment-cream text, muted gold accents, ember-red reserved for the Demon
// Lord. Panels sit on a slightly-opaque dark backing so text never fights the
// bright live world beneath.
export const COLORS = {
  ink: '#0b0e12', // deepest slate/charcoal (page backdrop)
  slate: '#14181f',
  panelBg: 'rgba(18, 22, 29, 0.84)', // translucent dark backing under text
  panelBgSolid: '#161b22',
  frameDark: '#241c12', // carved outer edge of a plate
  frameGold: 'rgba(201, 162, 75, 0.38)', // inset gold lip
  gold: '#c9a24b', // muted gold accent
  goldBright: '#e8c66a',
  cream: '#ece3cf', // parchment-cream body text
  creamDim: '#b3ab97',
  muted: '#8a8470',
  ember: '#d2563c', // RESERVED for the Demon Lord
  emberBright: '#e8714e',
  emberDim: '#7c3324',
  emberBg: 'rgba(58, 26, 20, 0.62)',
};

// A blocky display face for headers + a crisp readable face for body. Both are
// bundled (see theme.css @font-face → /assets/ui/fonts) and degrade to a
// monospace stack with no FOUT (font-display: block) if the binary is absent.
export const FONTS = {
  display: "'CV Display', 'Press Start 2P', 'Courier New', monospace",
  body: "'CV Body', 'VT323', ui-monospace, 'Courier New', monospace",
};

// Shared plate style for an overlay HUD card. Components spread this and add
// their own positioning. The matching `.cv-plate` CSS class layers the optional
// 9-slice frame PNG on top (no-ops to this CSS border when the PNG is absent).
export const plate = {
  background: COLORS.panelBg,
  border: `2px solid ${COLORS.frameDark}`,
  boxShadow: `inset 0 0 0 2px ${COLORS.frameGold}, inset 0 0 16px rgba(0,0,0,0.55), 0 4px 16px rgba(0,0,0,0.5)`,
  borderRadius: '3px',
  color: COLORS.cream,
  fontFamily: FONTS.body,
};

// A header label for a plate (blocky display font, muted gold).
export const plateHeading = {
  margin: 0,
  fontFamily: FONTS.display,
  fontSize: '11px',
  letterSpacing: '0.04em',
  color: COLORS.gold,
  textTransform: 'uppercase',
  textShadow: '0 1px 0 rgba(0,0,0,0.6)',
};

export default { COLORS, FONTS, plate, plateHeading };
