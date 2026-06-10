import { useEffect, useRef } from 'react';
import { sendInput } from './api';

export const TILE_SIZE = 16;
export const SCALE = 2;
const DISPLAY_TILE_SIZE = TILE_SIZE * SCALE;
const WIDTH = 800;
const HEIGHT = 600;

export default function GameCanvas({ gameState }) {
  const canvasRef = useRef(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) {
      return;
    }

    const context = canvas.getContext('2d');
    if (!context) {
      return;
    }

    context.clearRect(0, 0, WIDTH, HEIGHT);
    context.fillStyle = '#4f545a';
    context.fillRect(0, 0, WIDTH, HEIGHT);

    if (!gameState.tiles || gameState.tiles.length === 0) {
      context.fillStyle = '#f5f5f5';
      context.font = '20px sans-serif';
      context.textAlign = 'center';
      context.fillText('World not generated', WIDTH / 2, HEIGHT / 2);
      return;
    }

    for (const tile of gameState.tiles) {
      const color = tile.tile_type === 'water'
        ? '#255d8f'
        : tile.tile_type === 'stone_path'
          ? '#847867'
          : tile.tile_type === 'building_floor'
            ? '#b38b64'
            : tile.tile_type === 'building_wall'
              ? '#5a4738'
              : '#5c8c48';
      context.fillStyle = color;
      context.fillRect(tile.x * DISPLAY_TILE_SIZE, tile.y * DISPLAY_TILE_SIZE, DISPLAY_TILE_SIZE, DISPLAY_TILE_SIZE);
    }

    for (const npc of gameState.npcs ?? []) {
      context.fillStyle = '#f4d35e';
      context.fillRect(npc.x * DISPLAY_TILE_SIZE - 6, npc.y * DISPLAY_TILE_SIZE - 6, 12, 12);
    }

    if (gameState.player) {
      context.fillStyle = '#f76c6c';
      context.fillRect(gameState.player.x * DISPLAY_TILE_SIZE - 7, gameState.player.y * DISPLAY_TILE_SIZE - 7, 14, 14);
    }
  }, [gameState]);

  useEffect(() => {
    const onKeyDown = async (event) => {
      const directionMap = {
        ArrowUp: 'up',
        ArrowDown: 'down',
        ArrowLeft: 'left',
        ArrowRight: 'right'
      };

      const direction = directionMap[event.key];
      if (!direction) {
        return;
      }

      event.preventDefault();
      await sendInput({
        type: 'move',
        payload: { direction }
      });
    };

    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, []);

  const handleClick = async (event) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const scaleX = WIDTH / rect.width;
    const scaleY = HEIGHT / rect.height;
    const clickX = (event.clientX - rect.left) * scaleX;
    const clickY = (event.clientY - rect.top) * scaleY;

    for (const npc of gameState.npcs ?? []) {
      const npcX = npc.x * DISPLAY_TILE_SIZE;
      const npcY = npc.y * DISPLAY_TILE_SIZE;
      const distance = Math.hypot(clickX - npcX, clickY - npcY);
      if (distance <= 16) {
        await sendInput({
          type: 'interact',
          payload: { npc_id: npc.id }
        });
        break;
      }
    }
  };

  return (
    <canvas
      ref={canvasRef}
      width={WIDTH}
      height={HEIGHT}
      onClick={handleClick}
      style={styles.canvas}
      aria-label="Game world canvas"
    />
  );
}

const styles = {
  canvas: {
    width: '100%',
    height: 'auto',
    maxWidth: `${WIDTH}px`,
    border: '1px solid #2c313a',
    background: '#4f545a',
    display: 'block'
  }
};