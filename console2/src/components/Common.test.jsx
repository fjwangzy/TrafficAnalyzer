import { fireEvent, render, screen } from '@testing-library/react'
import { useState } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { DataTable, DetailDrawer, Segmented } from './Common'

describe('shared interactive components', () => {
  it('lets keyboard users activate an interactive table row', () => {
    const onRowClick = vi.fn()
    render(<DataTable columns={[{ key: 'name', label: '名称' }]} rows={[{ id: 'ROW-1', name: '测试任务' }]} onRowClick={onRowClick} />)
    const row = screen.getByRole('row', { name: '测试任务' })

    expect(row).toHaveAttribute('tabindex', '0')
    fireEvent.keyDown(row, { key: 'Enter' })
    fireEvent.keyDown(row, { key: ' ' })

    expect(onRowClick).toHaveBeenCalledTimes(2)
  })

  it('announces the selected segmented option', () => {
    render(<Segmented label='视图模式' value='map' onChange={vi.fn()} options={[{ value: 'map', label: '地图' }, { value: 'list', label: '列表' }]} />)
    expect(screen.getByRole('group', { name: '视图模式' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: '地图' })).toHaveAttribute('aria-pressed', 'true')
    expect(screen.getByRole('button', { name: '列表' })).toHaveAttribute('aria-pressed', 'false')
  })

  it('traps drawer focus, closes with Escape, and restores the trigger focus', () => {
    function Harness() {
      const [open, setOpen] = useState(false)
      return <><button onClick={() => setOpen(true)}>打开详情</button>{open && <DetailDrawer title='任务详情' onClose={() => setOpen(false)} footer={<button>保存</button>}><button>正文操作</button></DetailDrawer>}</>
    }
    render(<Harness />)
    const trigger = screen.getByRole('button', { name: '打开详情' })
    trigger.focus()
    fireEvent.click(trigger)

    expect(screen.getByRole('dialog', { name: '任务详情' })).toHaveAttribute('aria-modal', 'true')
    expect(screen.getByRole('button', { name: '关闭' })).toHaveFocus()
    fireEvent.keyDown(document, { key: 'Escape' })

    expect(screen.queryByRole('dialog')).not.toBeInTheDocument()
    expect(trigger).toHaveFocus()
  })
})
