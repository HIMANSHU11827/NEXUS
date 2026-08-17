import { useState, useEffect } from 'react'

const flowers = ['·', '✻', '✽', '✶', '✳', '✢']

export default function ClaudeAnimation() {
  const [flowerIndex, setFlowerIndex] = useState(0)

  useEffect(() => {
    const flowerInterval = setInterval(() => {
      setFlowerIndex(prev => (prev + 1) % flowers.length)
    }, 200)

    return () => {
      clearInterval(flowerInterval)
    }
  }, [])

  return (
    <span className="text-lg animate-pulse" style={{ animationDuration: '1.5s' }}>
      {flowers[flowerIndex]}
    </span>
  )
}
