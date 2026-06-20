import { useState } from 'react';
import { COLORS, FONTS } from './theme';

// Day 10 first-run title splash (Part F). Shown over a darkened world until the
// first user gesture. Clicking "Begin" both starts the game and satisfies the
// browser autoplay policy (audioManager.unlock(), wired in App), so the OST
// starts intentionally on this gesture instead of on a random later keypress.
// It then fades itself out and unmounts. Fully presentational — no payload, no
// intents; if the title/credits ever go missing the layout still holds.
export default function TitleSplash({ onBegin }) {
  const [leaving, setLeaving] = useState(false);

  const begin = () => {
    if (leaving) return;
    setLeaving(true); // play the fade; App unmounts us after it settles
    onBegin();
  };

  return (
    <div
      style={{ ...styles.backdrop, opacity: leaving ? 0 : 1, pointerEvents: leaving ? 'none' : 'auto' }}
      onClick={begin}
      role="button"
      aria-label="Begin"
    >
      <div style={styles.center}>
        <div style={styles.kicker}>A LIVING-WORLD RPG</div>
        <h1 style={styles.title}>Chronicle</h1>
        <div style={styles.subtitle}>of the Velvet Lies</div>
        <div style={styles.rule} />
        <button className="cv-btn cv-btn-primary" style={styles.begin} onClick={begin}>
          ▶ Click to begin
        </button>
        <div style={styles.hint}>Sound begins on your first click</div>
      </div>
    </div>
  );
}

const styles = {
  backdrop: {
    position: 'fixed',
    inset: 0,
    zIndex: 80,
    display: 'flex',
    alignItems: 'center',
    justifyContent: 'center',
    background:
      'radial-gradient(ellipse at center, rgba(14,17,22,0.86) 0%, rgba(7,9,12,0.96) 100%)',
    transition: 'opacity 0.8s ease',
    cursor: 'pointer',
  },
  center: {
    textAlign: 'center',
    padding: '40px',
    animation: 'cvFadeIn 1.1s ease both',
  },
  kicker: {
    fontFamily: FONTS.body,
    fontSize: '13px',
    letterSpacing: '0.42em',
    color: COLORS.muted,
    marginBottom: '18px',
    paddingLeft: '0.42em',
  },
  title: {
    margin: 0,
    fontFamily: FONTS.display,
    fontSize: '52px',
    letterSpacing: '0.04em',
    color: COLORS.goldBright,
    textShadow: '0 3px 0 rgba(0,0,0,0.7), 0 0 22px rgba(201,162,75,0.25)',
  },
  subtitle: {
    marginTop: '10px',
    fontFamily: FONTS.display,
    fontSize: '20px',
    letterSpacing: '0.06em',
    color: COLORS.cream,
    textShadow: '0 2px 0 rgba(0,0,0,0.7)',
  },
  rule: {
    width: '180px',
    height: '2px',
    margin: '26px auto',
    background:
      'linear-gradient(90deg, rgba(201,162,75,0) 0%, rgba(201,162,75,0.7) 50%, rgba(201,162,75,0) 100%)',
  },
  begin: {
    fontSize: '15px',
    padding: '12px 26px',
  },
  hint: {
    marginTop: '16px',
    fontFamily: FONTS.body,
    fontSize: '12px',
    color: COLORS.muted,
  },
};
