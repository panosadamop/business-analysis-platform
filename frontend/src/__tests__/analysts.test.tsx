/** Choosing a project's AI analysts. */
import { useState } from 'react'
import { describe, expect, it } from 'vitest'
import { render, screen } from '@testing-library/react'
import userEvent from '@testing-library/user-event'

import {
  ALL_ANALYSTS, AnalystPicker, DEFAULT_ANALYSTS, sortAnalysts,
} from '../components/analysts'
import type { AnalystRole } from '../types'

function Harness({ initial = ALL_ANALYSTS }: { initial?: AnalystRole[] }) {
  const [value, setValue] = useState<AnalystRole[]>(initial)
  return (
    <>
      <AnalystPicker value={value} onChange={setValue} />
      <output>{value.join(',')}</output>
    </>
  )
}

describe('analyst picker', () => {
  it('lists the five analysts as a labelled group, UX and data off by default', () => {
    render(<Harness initial={DEFAULT_ANALYSTS} />)
    expect(screen.getByRole('group', { name: 'Analysts' })).toBeInTheDocument()
    for (const name of [/Business analyst/, /Technical analyst/, /QA analyst/]) {
      expect(screen.getByRole('checkbox', { name })).toBeChecked()
    }
    expect(screen.getByRole('checkbox', { name: /UX analyst/ })).not.toBeChecked()
    expect(screen.getByRole('checkbox', { name: /Data analyst/ })).not.toBeChecked()
  })

  it('places the UX and data analysts after the business analyst', async () => {
    render(<Harness initial={DEFAULT_ANALYSTS} />)
    await userEvent.click(screen.getByRole('checkbox', { name: /Data analyst/ }))
    await userEvent.click(screen.getByRole('checkbox', { name: /UX analyst/ }))
    expect(screen.getByRole('status')).toHaveTextContent(
      'business_analyst,ux_analyst,data_analyst,technical_analyst,qa_analyst')
  })

  it('keeps the choice in run order whatever order it is made in', async () => {
    render(<Harness initial={['qa_analyst']} />)
    await userEvent.click(screen.getByRole('checkbox', { name: /Business analyst/ }))
    expect(screen.getByRole('status')).toHaveTextContent('business_analyst,qa_analyst')
  })

  it('never lets the last analyst be switched off', async () => {
    render(<Harness initial={['technical_analyst', 'qa_analyst']} />)
    await userEvent.click(screen.getByRole('checkbox', { name: /QA analyst/ }))
    expect(screen.getByRole('checkbox', { name: /Technical analyst/ })).toBeDisabled()
    expect(screen.getByText(/The only analyst left/)).toBeInTheDocument()
    expect(screen.getByRole('status')).toHaveTextContent('technical_analyst')
  })

  it('sorts any selection into run order', () => {
    expect(sortAnalysts(['qa_analyst', 'business_analyst'])).toEqual(
      ['business_analyst', 'qa_analyst'])
  })
})
