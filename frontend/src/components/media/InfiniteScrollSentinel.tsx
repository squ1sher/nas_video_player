import { useEffect, useRef } from "react";

type Props = {
  onVisible: () => void;
  disabled?: boolean;
};

/** Renders an invisible sentinel that calls `onVisible` when scrolled into view. */
export function InfiniteScrollSentinel({ onVisible, disabled = false }: Props) {
  const ref = useRef<HTMLDivElement | null>(null);
  const callbackRef = useRef(onVisible);
  callbackRef.current = onVisible;

  useEffect(() => {
    if (disabled) return;
    const node = ref.current;
    if (!node) return;

    const observer = new IntersectionObserver(
      (entries) => {
        if (entries.some((entry) => entry.isIntersecting)) {
          callbackRef.current();
        }
      },
      { rootMargin: "200px" }
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [disabled]);

  return <div ref={ref} className="infinite-scroll-sentinel" aria-hidden="true" />;
}
