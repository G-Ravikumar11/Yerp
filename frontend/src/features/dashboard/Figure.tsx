import { useEffect, useRef, useState } from 'react'
import { animate, useReducedMotion } from 'framer-motion'

/**
 * A figure that counts to its value instead of appearing. It only animates
 * when the number changes, never on a re-render, and not at all for anyone
 * who has asked their device for less motion.
 */
export function Figure({ value, format }: { value: number; format: (n: number) => string }) {
  const calm = useReducedMotion()
  const [shown, setShown] = useState(calm ? value : 0)
  const from = useRef(calm ? value : 0)

  useEffect(() => {
    if (calm) {
      setShown(value)
      return
    }
    const controls = animate(from.current, value, {
      duration: 0.9,
      ease: [0.16, 1, 0.3, 1],
      onUpdate: (n) => setShown(n),
      onComplete: () => {
        from.current = value
      },
    })
    return () => controls.stop()
  }, [value, calm])

  return <>{format(shown)}</>
}
