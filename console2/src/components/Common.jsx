import { useEffect, useRef } from 'react'
import { CaretRight, CheckCircle, Info, WarningCircle, XCircle } from '@phosphor-icons/react'
import { statusLabel } from '../data/mockData'

export function StatusBadge({ value, children }) {
  return <span className={`status-badge ${value}`}>{children || statusLabel[value] || value}</span>
}

export function PageHeader({ title, actions }) {
  return <>
    <h1 className='sr-only'>{title}</h1>
    {actions && <div className='page-actions'>{actions}</div>}
  </>
}

export function Panel({ title, subtitle, action, className = '', children }) {
  return (
    <section className={`surface-panel ${className}`}>
      {(title || action) && <header className='panel-title'><div><strong>{title}</strong>{subtitle && <span>{subtitle}</span>}</div>{action}</header>}
      {children}
    </section>
  )
}

export function KpiCard({ icon: Icon, label, value, unit, change, tone = 'blue', detail }) {
  return (
    <article className={`kpi-card tone-${tone}`}>
      <span className='kpi-icon'><Icon size={20} weight='duotone' /></span>
      <div className='kpi-copy'><span>{label}</span><strong>{value}<small>{unit}</small></strong>{detail && <em>{detail}</em>}</div>
      {change && <span className='kpi-change'>{change}</span>}
    </article>
  )
}

export function DataTable({ columns, rows, rowKey = 'id', onRowClick, empty = '暂无符合条件的数据' }) {
  return (
    <div className='data-table-wrap'>
      <table className='data-table'>
        <thead><tr>{columns.map((column) => <th key={column.key}>{column.label}</th>)}</tr></thead>
        <tbody>
          {rows.length === 0 && <tr><td colSpan={columns.length} className='empty-cell'>{empty}</td></tr>}
          {rows.map((row) => (
            <tr key={row[rowKey]} tabIndex={onRowClick ? 0 : undefined} onClick={() => onRowClick?.(row)} onKeyDown={(event) => {
              if (!onRowClick || !['Enter', ' '].includes(event.key)) return
              event.preventDefault()
              onRowClick(row)
            }} className={onRowClick ? 'clickable' : ''}>
              {columns.map((column) => <td key={column.key}>{column.render ? column.render(row[column.key], row) : row[column.key]}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

export function FilterBar({ children, result, onReset }) {
  return <div className='filter-bar'><div className='filter-fields'>{children}</div><div className='filter-result'>{result && <span>{result}</span>}{onReset && <button className='text-button' onClick={onReset}>清空筛选</button>}</div></div>
}

export function Segmented({ value, onChange, options, label }) {
  return <div className='segmented' role='group' aria-label={label}>{options.map((item) => <button key={item.value} aria-pressed={value === item.value} className={value === item.value ? 'active' : ''} onClick={() => onChange(item.value)}>{item.label}</button>)}</div>
}

export function DetailDrawer({ title, subtitle, onClose, children, footer, wide = false }) {
  const drawerRef = useRef(null)
  const closeRef = useRef(null)
  const returnFocusRef = useRef(document.activeElement)
  useEffect(() => {
    closeRef.current?.focus()
    const handleKeyDown = (event) => {
      if (event.key === 'Escape') {
        event.preventDefault()
        onClose()
        return
      }
      if (event.key !== 'Tab') return
      const focusable = [...drawerRef.current.querySelectorAll('button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])')]
      if (!focusable.length) return
      const first = focusable[0]
      const last = focusable.at(-1)
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault(); last.focus()
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault(); first.focus()
      }
    }
    document.addEventListener('keydown', handleKeyDown)
    return () => {
      document.removeEventListener('keydown', handleKeyDown)
      returnFocusRef.current?.focus?.()
    }
  }, [onClose])
  return (
    <aside ref={drawerRef} className={`detail-drawer ${wide ? 'wide' : ''}`} role='dialog' aria-modal='true' aria-label={title}>
      <header><div><span>{subtitle}</span><strong>{title}</strong></div><button ref={closeRef} className='icon-action' onClick={onClose} aria-label='关闭'><XCircle size={21} /></button></header>
      <div className='drawer-body'>{children}</div>
      {footer && <footer>{footer}</footer>}
    </aside>
  )
}

export function InfoRow({ label, value, badge }) {
  return <div className='info-row'><span>{label}</span><strong>{badge ? <StatusBadge value={badge}>{value}</StatusBadge> : value}</strong></div>
}

export function QualityNotice({ tone = 'info', title, children }) {
  const icons = { info: Info, warning: WarningCircle, danger: XCircle, success: CheckCircle }
  const Icon = icons[tone] || Info
  return <div className={`quality-notice ${tone}`}><Icon size={18} weight='fill' /><div><strong>{title}</strong><span>{children}</span></div></div>
}

export function WorkflowSteps({ steps, active }) {
  return <ol className='workflow-steps'>{steps.map((step, index) => <li key={step} className={index < active ? 'done' : index === active ? 'active' : ''}><span>{index + 1}</span><strong>{step}</strong>{index < steps.length - 1 && <CaretRight size={14} />}</li>)}</ol>
}

export function EmptyState({ icon: Icon, title, description, action }) {
  return <div className='empty-state'><Icon size={36} weight='duotone' /><strong>{title}</strong><span>{description}</span>{action}</div>
}
