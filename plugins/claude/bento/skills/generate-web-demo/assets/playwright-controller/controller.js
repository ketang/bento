(() => {
  const state = {
    paused: false,
    stepping: false,
    stopped: false,
    currentStep: "",
    delayMs: 0,
    waiters: [],
  };

  const root = document.createElement("div");
  root.setAttribute("data-demo-controller", "true");
  root.style.cssText = [
    "position:fixed",
    "right:12px",
    "bottom:12px",
    "z-index:2147483647",
    "display:flex",
    "align-items:center",
    "gap:6px",
    "padding:8px",
    "border:1px solid rgba(0,0,0,.2)",
    "border-radius:6px",
    "background:rgba(255,255,255,.96)",
    "color:#111",
    "font:12px/1.3 system-ui,-apple-system,Segoe UI,sans-serif",
    "box-shadow:0 4px 18px rgba(0,0,0,.18)",
  ].join(";");

  const label = document.createElement("span");
  label.style.cssText = "max-width:260px;white-space:nowrap;overflow:hidden;text-overflow:ellipsis";

  function button(text, title, onClick) {
    const el = document.createElement("button");
    el.type = "button";
    el.textContent = text;
    el.title = title;
    el.style.cssText = [
      "border:1px solid rgba(0,0,0,.25)",
      "border-radius:4px",
      "background:#fff",
      "color:#111",
      "padding:4px 7px",
      "font:12px system-ui,-apple-system,Segoe UI,sans-serif",
      "cursor:pointer",
    ].join(";");
    el.addEventListener("click", onClick);
    return el;
  }

  function releaseWaiters() {
    const waiters = state.waiters.splice(0);
    for (const resolve of waiters) resolve();
  }

  function render() {
    label.textContent = state.currentStep ? `Step: ${state.currentStep}` : "Demo controller";
    pause.textContent = state.paused ? "Resume" : "Pause";
  }

  const pause = button("Pause", "Pause or resume the walkthrough", () => {
    state.paused = !state.paused;
    if (!state.paused) releaseWaiters();
    render();
  });
  const next = button("Next", "Run the next walkthrough step", () => {
    state.stepping = true;
    releaseWaiters();
  });
  const stop = button("Stop", "Stop the walkthrough at the next controller checkpoint", () => {
    state.stopped = true;
    releaseWaiters();
  });

  root.append(label, pause, next, stop);
  document.documentElement.appendChild(root);

  window.__webDemoController = {
    setStep(name) {
      state.currentStep = String(name || "");
      render();
    },
    setDelay(ms) {
      state.delayMs = Math.max(0, Number(ms) || 0);
    },
    pause() {
      state.paused = true;
      render();
    },
    resume() {
      state.paused = false;
      releaseWaiters();
      render();
    },
    async beforeStep(name) {
      this.setStep(name);
      if (state.delayMs > 0) {
        await new Promise((resolve) => setTimeout(resolve, state.delayMs));
      }
      while (state.paused && !state.stepping && !state.stopped) {
        await new Promise((resolve) => state.waiters.push(resolve));
      }
      if (state.stopped) throw new Error("Demo stopped by controller");
      state.stepping = false;
    },
    hideForScreenshot() {
      root.style.visibility = "hidden";
    },
    showAfterScreenshot() {
      root.style.visibility = "visible";
    },
  };

  render();
})();
