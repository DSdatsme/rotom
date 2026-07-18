"use client";

import { useEffect, useRef } from "react";
import { onRotomMotion } from "@/lib/rotom-motion";

/**
 * The rotom mark: a living lightning bolt with black pupil-eyes.
 * Motions — idle blink (ambient), buzz on hover, eye-dart while typing,
 * wink on an action. Typing/wink arrive over the shared motion bus; buzz is CSS
 * `:hover` (on the mark itself or any [data-rotom-hover] ancestor, so hovering an
 * adjacent wordmark counts too). All fall back to static under reduced-motion.
 */
export function RotomMark({
  size = 24,
  className = "",
  title = "rotom",
}: {
  size?: number;
  className?: string;
  title?: string;
}) {
  const eyesRef = useRef<SVGGElement>(null);
  const eyeRRef = useRef<SVGEllipseElement>(null);
  const winking = useRef(false);
  const typingTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    const eyes = eyesRef.current;
    const eyeR = eyeRRef.current;
    if (!eyes || !eyeR) return;

    const setBase = (base: "idle" | "typing") => {
      if (winking.current) return;
      eyes.classList.remove("is-idle", "is-typing");
      eyes.classList.add(base === "typing" ? "is-typing" : "is-idle");
    };
    setBase("idle");

    const onTyping = () => {
      setBase("typing");
      if (typingTimer.current) clearTimeout(typingTimer.current);
      typingTimer.current = setTimeout(() => {
        typingTimer.current = null;
        setBase("idle");
      }, 900);
    };
    const onWink = () => {
      winking.current = true;
      eyes.classList.remove("is-idle", "is-typing"); // pause the group so only the wink reads
      eyeR.classList.remove("is-wink");
      void eyeR.getBoundingClientRect(); // reflow → restart even on rapid clicks
      eyeR.classList.add("is-wink");
    };
    const onWinkEnd = () => {
      if (!eyeR.classList.contains("is-wink")) return;
      eyeR.classList.remove("is-wink");
      winking.current = false;
      eyes.classList.add(typingTimer.current ? "is-typing" : "is-idle");
    };
    eyeR.addEventListener("animationend", onWinkEnd);

    const offTyping = onRotomMotion("typing", onTyping);
    const offWink = onRotomMotion("wink", onWink);
    return () => {
      offTyping();
      offWink();
      eyeR.removeEventListener("animationend", onWinkEnd);
      if (typingTimer.current) clearTimeout(typingTimer.current);
    };
  }, []);

  return (
    <svg
      className={`rotom-mark ${className}`}
      width={size}
      height={size}
      viewBox="14 3 36 58"
      role="img"
      aria-label={title}
    >
      <defs>
        <linearGradient id="rotom-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="#a488ff" />
          <stop offset="1" stopColor="#6d4fe0" />
        </linearGradient>
      </defs>
      <g className="rl-body">
        <path d="M36 6 L16 34 H27 L23 58 L49 26 H37 L43 6 Z" fill="url(#rotom-grad)" />
        {/* eyesRef = dart (screen-horizontal); inner group = static -12° tilt so the
            blink/wink animations stay pure scaleY and never fight an attribute rotate */}
        <g ref={eyesRef}>
          <g transform="rotate(-12 32 20)">
            <ellipse cx="28.5" cy="21" rx="2.4" ry="3.9" fill="#141220" />
            <ellipse ref={eyeRRef} cx="35.5" cy="19" rx="2.4" ry="3.9" fill="#141220" />
          </g>
        </g>
      </g>
    </svg>
  );
}
