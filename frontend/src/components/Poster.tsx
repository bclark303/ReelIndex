import { useState } from 'react'
import { Icon } from './Icon'

export function Poster({ src, title, className = '' }: { src?: string | null; title: string; className?: string }) {
  const [failed, setFailed] = useState(false)
  if (!src || failed) {
    return <div className={`poster-placeholder ${className}`} role="img" aria-label={`No poster available for ${title}`}><Icon name="film" size={38}/><span>{title.slice(0, 1).toUpperCase()}</span></div>
  }
  return <img className={className} src={src} alt={`${title} poster`} loading="lazy" onError={() => setFailed(true)} />
}
