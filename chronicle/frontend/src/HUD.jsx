function formatHour(hour) {
  const h = Number.isFinite(hour) ? ((hour % 24) + 24) % 24 : 0;
  return `${String(h).padStart(2, '0')}:00`;
}

export default function HUD({ gameState }) {
  const factionEntries = Object.entries(gameState.faction_reputations ?? {});
  const factionMorale = gameState.faction_morale ?? {};
  const recentNotifications = (gameState.notifications ?? []).slice(-3);
  const player = gameState.player;
  // Display-ready strings straight from the backend payload (Day 6).
  const rumors = gameState.rumors ?? [];
  const demonLordDecisions = gameState.demon_lord_decisions ?? [];

  return (
    <aside style={styles.panel}>
      <section>
        <h2 style={styles.heading}>World</h2>
        <div>Day: {gameState.current_day}</div>
        <div>
          Time: {formatHour(gameState.current_hour)} ({gameState.time_of_day})
          {gameState.world_paused ? <span style={styles.paused}> ⏸ paused</span> : null}
        </div>
        <div>Weather: {gameState.weather}</div>
      </section>

      {player ? (
        <section style={styles.section}>
          <h2 style={styles.heading}>You</h2>
          <div>{player.name}</div>
          {player.occupation ? <div style={styles.muted}>{player.occupation}</div> : null}
        </section>
      ) : null}

      <section style={styles.section}>
        <h2 style={styles.heading}>Factions</h2>
        {factionEntries.length === 0 ? (
          <div style={styles.muted}>No factions yet.</div>
        ) : (
          factionEntries.map(([name, score]) => (
            <div key={name} style={styles.row}>
              <span>{name}</span>
              <span>
                {score}
                {name in factionMorale ? (
                  <span style={styles.muted}> · morale {factionMorale[name]}</span>
                ) : null}
              </span>
            </div>
          ))
        )}
        <div style={styles.legend}>standing toward you · faction morale</div>
      </section>

      <section style={styles.section}>
        <h2 style={styles.heading}>Demon Lord</h2>
        {demonLordDecisions.length === 0 ? (
          <div style={styles.muted}>No sign of the Demon Lord yet.</div>
        ) : (
          demonLordDecisions.map((item, index) => (
            <div key={`${item}-${index}`} style={styles.demonLord}>
              {item}
            </div>
          ))
        )}
      </section>

      <section style={styles.section}>
        <h2 style={styles.heading}>Rumors Abroad</h2>
        {rumors.length === 0 ? (
          <div style={styles.muted}>The town is quiet.</div>
        ) : (
          rumors.map((item, index) => (
            <div key={`${item}-${index}`} style={styles.rumor}>
              {item}
            </div>
          ))
        )}
      </section>

      <section style={styles.section}>
        <h2 style={styles.heading}>Recent Notifications</h2>
        {recentNotifications.length === 0 ? (
          <div style={styles.muted}>Nothing to report.</div>
        ) : (
          recentNotifications.map((item, index) => (
            <div key={`${item}-${index}`} style={styles.notification}>
              {item}
            </div>
          ))
        )}
      </section>
    </aside>
  );
}

const styles = {
  panel: {
    minHeight: '100%',
    background: '#171b22',
    border: '1px solid #2c313a',
    padding: '16px',
    boxSizing: 'border-box'
  },
  section: {
    marginTop: '20px'
  },
  heading: {
    margin: '0 0 8px',
    fontSize: '16px'
  },
  row: {
    display: 'flex',
    justifyContent: 'space-between',
    gap: '12px',
    padding: '4px 0'
  },
  notification: {
    padding: '6px 0',
    borderBottom: '1px solid #262c35'
  },
  demonLord: {
    padding: '6px 0',
    borderBottom: '1px solid #3a2026',
    color: '#e08a8a'
  },
  rumor: {
    padding: '6px 0',
    borderBottom: '1px solid #262c35',
    color: '#c9b97e',
    fontStyle: 'italic'
  },
  muted: {
    color: '#9ca3af'
  },
  legend: {
    color: '#6b7280',
    fontSize: '11px',
    marginTop: '6px'
  },
  paused: {
    color: '#8ab4f8'
  }
};