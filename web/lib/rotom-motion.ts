// Client-side motion bus for the rotom logo mark.
//
// Two global signals drive the mark's animations without wiring every widget:
//   - typing on any text field  -> "typing"  (eye dart)
//   - click on any [data-rotom-wink] control -> "wink"
// Callers can also fire rotomWink()/rotomTyping() imperatively. The RotomMark
// component subscribes via onRotomMotion(); listeners install lazily on first use.

type MotionEvent = "typing" | "wink";

const bus: EventTarget | null = typeof window !== "undefined" ? new EventTarget() : null;

let installed = false;
function installGlobalListeners() {
  if (installed || !bus || typeof document === "undefined") return;
  installed = true;

  // Any real text entry, anywhere, reads as "the spirit is reading along."
  document.addEventListener(
    "input",
    (e) => {
      const t = e.target as HTMLElement | null;
      if (!t) return;
      const isText =
        t.tagName === "TEXTAREA" ||
        t.isContentEditable ||
        (t.tagName === "INPUT" && /^(|text|search|email|url|tel)$/i.test((t as HTMLInputElement).type));
      if (isText) bus!.dispatchEvent(new Event("typing"));
    },
    true,
  );

  // Any control opting in with data-rotom-wink acknowledges the action.
  document.addEventListener(
    "click",
    (e) => {
      const el = (e.target as HTMLElement | null)?.closest("[data-rotom-wink]");
      if (el) bus!.dispatchEvent(new Event("wink"));
    },
    true,
  );
}

export function onRotomMotion(type: MotionEvent, cb: () => void): () => void {
  installGlobalListeners();
  if (!bus) return () => {};
  bus.addEventListener(type, cb);
  return () => bus.removeEventListener(type, cb);
}

export function rotomWink() {
  bus?.dispatchEvent(new Event("wink"));
}

export function rotomTyping() {
  bus?.dispatchEvent(new Event("typing"));
}
