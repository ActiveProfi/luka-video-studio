import { useEffect, useRef } from 'react';
import './LukaEyes.css';

export default function LukaEyes() {
  const mark = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const node = mark.current;
    if (!node) return;
    const motion = window.matchMedia('(prefers-reduced-motion: reduce)');
    let frame = 0;
    let pointerX = 0;
    let pointerY = 0;

    const update = () => {
      frame = 0;
      if (motion.matches) {
        node.style.setProperty('--eye-x', '0px');
        node.style.setProperty('--eye-y', '0px');
        return;
      }
      const rect = node.getBoundingClientRect();
      const dx = pointerX - (rect.left + rect.width / 2);
      const dy = pointerY - (rect.top + rect.height / 2);
      const length = Math.hypot(dx, dy) || 1;
      const distance = Math.min(length / 32, 1);
      node.style.setProperty('--eye-x', `${(dx / length * 3.5 * distance).toFixed(2)}px`);
      node.style.setProperty('--eye-y', `${(dy / length * 3 * distance).toFixed(2)}px`);
    };
    const move = (event: PointerEvent) => {
      pointerX = event.clientX;
      pointerY = event.clientY;
      if (!frame) frame = requestAnimationFrame(update);
    };
    window.addEventListener('pointermove', move, { passive: true });
    motion.addEventListener('change', update);
    return () => {
      window.removeEventListener('pointermove', move);
      motion.removeEventListener('change', update);
      cancelAnimationFrame(frame);
    };
  }, []);

  return <span ref={mark} className="luka-eyes" aria-hidden="true">
    <span className="luka-eye"><span className="luka-pupil"/></span>
    <span className="luka-eye"><span className="luka-pupil"/></span>
  </span>;
}
