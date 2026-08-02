import { Icon } from './Icon'

export function EmptyState({ title, message, action }: { title: string; message: string; action?: React.ReactNode }) {
  return <div className="empty-state"><div className="empty-icon"><Icon name="film" size={34}/></div><h2>{title}</h2><p>{message}</p>{action}</div>
}
