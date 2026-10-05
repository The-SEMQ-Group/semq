/* A schematic morph: an irregular continuous surface folds into a discrete
   spherical lattice. It illustrates a mapping, not the codec's literal output. */
(() => {
  const WIDTH = 520;
  const HEIGHT = 340;
  const CENTER_X = WIDTH / 2;
  const CENTER_Y = HEIGHT / 2;
  const RADIUS = 152;
  const ROWS = 17;
  const COLS = 21;
  const CYCLE_MS = 10000;
  const nodes = [];
  const edges = [];
  const highlighted = new Map([
    [45, "#4ba3c9"], [98, "#8668b7"], [131, "#f0a34b"],
    [179, "#4ba3c9"], [227, "#8668b7"], [258, "#f0a34b"],
    [308, "#4ba3c9"]
  ]);

  for (let row = 0; row < ROWS; row++) {
    const latitude = -Math.PI / 2 + (row / (ROWS - 1)) * Math.PI;
    for (let col = 0; col < COLS; col++) {
      const longitude = -Math.PI / 2 + (col / (COLS - 1)) * Math.PI;
      const bulge = Math.cos(latitude);
      const distance = Math.hypot(
        (row - (ROWS - 1) / 2) / ((ROWS - 1) / 2),
        (col - (COLS - 1) / 2) / ((COLS - 1) / 2)
      ) / Math.SQRT2;
      nodes.push({
        sourceX: 52 + col * (416 / (COLS - 1)) + Math.sin(row * .85 + col * .31) * 9,
        sourceY: 54 + row * (232 / (ROWS - 1)) + Math.sin(col * .61 + row * .37) * 17,
        latitude,
        longitude,
        bulge,
        delay: distance * .14
      });
      if (col) edges.push([row * COLS + col - 1, row * COLS + col]);
      if (row) edges.push([(row - 1) * COLS + col, row * COLS + col]);
    }
  }

  const smooth = value => {
    const x = Math.max(0, Math.min(1, value));
    return x * x * (3 - 2 * x);
  };
  const mix = (a, b, t) => a + (b - a) * t;

  let cleanup = () => {};
  function init() {
    cleanup();
    const visual = document.querySelector("[data-geometry]");
    if (!visual) return;
    const canvas = visual.querySelector("canvas");
    const context = canvas.getContext("2d");
    if (!context) return;
    const reducedMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const ratio = Math.min(window.devicePixelRatio || 1, 2);
    canvas.width = Math.round(WIDTH * ratio);
    canvas.height = Math.round(HEIGHT * ratio);
    context.setTransform(ratio, 0, 0, ratio, 0, 0);

    let frame = 0;
    let visible = false;
    let elapsed = reducedMotion ? 5000 : 0;
    let lastTime = 0;
    let lastPaint = 0;
    function draw(progress) {
      const stroke = "#7595a8";
      const dust = "#9cb6c2";
      const center = "#e6f3f9";
      context.clearRect(0, 0, WIDTH, HEIGHT);

      const wash = context.createRadialGradient(CENTER_X, CENTER_Y, 10, CENTER_X, CENTER_Y, RADIUS);
      wash.addColorStop(0, "rgba(75,163,201,.08)");
      wash.addColorStop(1, "rgba(75,163,201,0)");
      context.fillStyle = wash;
      context.fillRect(70, 0, 380, HEIGHT);

      context.save();
      context.globalAlpha = .38 * progress;
      const volume = context.createRadialGradient(210, 100, 2, CENTER_X, CENTER_Y, RADIUS + 15);
      volume.addColorStop(0, "rgba(89,178,209,.18)");
      volume.addColorStop(1, "rgba(89,178,209,0)");
      context.fillStyle = volume;
      context.beginPath();
      context.arc(CENTER_X, CENTER_Y, RADIUS, 0, Math.PI * 2);
      context.fill();
      context.globalAlpha = .22 * smooth((progress - .88) / .12);
      context.strokeStyle = stroke;
      context.lineWidth = 1;
      context.setLineDash([2, 5]);
      context.beginPath();
      context.ellipse(CENTER_X, CENTER_Y, RADIUS * .52, RADIUS, 0, 0, Math.PI * 2);
      context.stroke();
      context.restore();

      // Orthographic projection: at longitude ±π/2 the mesh lies exactly on
      // the rim (x² + y² = R²), including both poles. Screen-plane rotation
      // preserves that invariant throughout the spherical hold.
      const rotation = .055 * progress * Math.sin(elapsed / 1300);
      const cosine = Math.cos(rotation);
      const sine = Math.sin(rotation);
      const points = nodes.map(node => {
        const local = smooth((progress - node.delay) / (1 - node.delay));
        const sphereX = RADIUS * node.bulge * Math.sin(node.longitude);
        const sphereY = -RADIUS * Math.sin(node.latitude);
        const sourceY = node.sourceY + Math.sin(elapsed / 950 + node.longitude * 2 + node.latitude) * 2.5;
        return {
          x: mix(node.sourceX, CENTER_X + sphereX * cosine - sphereY * sine, local),
          y: mix(sourceY, CENTER_Y + sphereX * sine + sphereY * cosine, local),
          depth: node.bulge * Math.cos(node.longitude)
        };
      });
      // Draw the rim from the very same boundary vertices as the lattice.
      // It folds with the surface and cannot drift away from its outer edge.
      context.save();
      context.strokeStyle = stroke;
      context.globalAlpha = .13 + progress * .27;
      context.lineWidth = 1.1;
      context.lineJoin = "round";
      context.beginPath();
      context.moveTo(points[0].x, points[0].y);
      for (let col = 1; col < COLS; col++) context.lineTo(points[col].x, points[col].y);
      for (let row = 1; row < ROWS; row++) {
        const point = points[row * COLS + COLS - 1];
        context.lineTo(point.x, point.y);
      }
      for (let col = COLS - 2; col >= 0; col--) {
        const point = points[(ROWS - 1) * COLS + col];
        context.lineTo(point.x, point.y);
      }
      for (let row = ROWS - 2; row > 0; row--) {
        const point = points[row * COLS];
        context.lineTo(point.x, point.y);
      }
      context.closePath();
      context.stroke();
      context.restore();
      context.save();
      context.strokeStyle = stroke;
      context.lineWidth = .8;
      context.globalAlpha = .11 + progress * .13;
      context.beginPath();
      for (const [a, b] of edges) {
        context.moveTo(points[a].x, points[a].y);
        context.lineTo(points[b].x, points[b].y);
      }
      context.stroke();
      context.restore();

      const convergence = Math.exp(-Math.pow((progress - .91) / .07, 2));
      context.save();
      context.globalAlpha = convergence * .52;
      context.strokeStyle = "#4ba3c9";
      context.shadowColor = context.strokeStyle;
      context.shadowBlur = 15;
      context.lineWidth = 1.4;
      context.beginPath();
      const sweep = -Math.PI / 2 + elapsed / 520;
      context.arc(CENTER_X, CENTER_Y, RADIUS + 3, sweep, sweep + 1.1);
      context.stroke();
      context.restore();

      points.forEach((point, index) => {
        const accent = highlighted.get(index);
        const radius = accent ? mix(2.8, 5.1, progress) : mix(1.1, 1.45, progress);
        context.save();
        context.globalAlpha = accent ? .92 : mix(.5, .77, progress) * (.68 + point.depth * .32);
        context.fillStyle = accent || dust;
        if (accent) {
          context.shadowColor = accent;
          context.shadowBlur = 8 + progress * 12;
        }
        context.beginPath();
        context.arc(point.x, point.y, radius, 0, Math.PI * 2);
        context.fill();
        if (accent && convergence > .03) {
          context.shadowBlur = 0;
          context.globalAlpha = convergence * .35;
          context.strokeStyle = accent;
          context.lineWidth = .9;
          context.beginPath();
          context.arc(point.x, point.y, radius + 5 + 8 * (1 - convergence), 0, Math.PI * 2);
          context.stroke();
        }
        context.restore();
      });

      context.save();
      context.globalAlpha = .5 * progress;
      context.fillStyle = center;
      context.beginPath();
      context.arc(CENTER_X, CENTER_Y, 2.2, 0, Math.PI * 2);
      context.fill();
      context.restore();
    }

    function stateAt(milliseconds) {
      const t = milliseconds % CYCLE_MS;
      if (t < 1400) return 0;
      if (t < 4200) return smooth((t - 1400) / 2800);
      if (t < 7400) return 1;
      if (t < 9400) return 1 - smooth((t - 7400) / 2000);
      return 0;
    }

    function paint() {
      draw(stateAt(elapsed));
    }
    function tick(now) {
      if (!visible || document.hidden) { frame = 0; lastTime = 0; return; }
      if (lastTime) elapsed += Math.min(now - lastTime, 100);
      lastTime = now;
      if (now - lastPaint >= 30) { paint(); lastPaint = now; }
      frame = requestAnimationFrame(tick);
    }
    function schedule() {
      if (!frame && !reducedMotion && visible && !document.hidden) frame = requestAnimationFrame(tick);
    }
    function onVisibility() {
      if (document.hidden) { cancelAnimationFrame(frame); frame = 0; lastTime = 0; }
      else schedule();
    }
    const observer = new IntersectionObserver(entries => {
      visible = entries[0].isIntersecting;
      if (!visible) { cancelAnimationFrame(frame); frame = 0; lastTime = 0; }
      else schedule();
    }, { threshold: .1 });
    document.addEventListener("visibilitychange", onVisibility);
    paint();
    visual.classList.add("is-ready");
    observer.observe(canvas);
    cleanup = () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }

  if (typeof document$ !== "undefined") document$.subscribe(init);
  else if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", init);
  else init();
})();
