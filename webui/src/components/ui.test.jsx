import { describe, it, expect, vi } from 'vitest'
import { render, screen, fireEvent } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { Button, Badge, Input, Switch, Textarea, Select, Card } from './ui'

// ---------------------------------------------------------------------------
// Button
// ---------------------------------------------------------------------------
describe('Button', () => {
  it('renders children', () => {
    render(<Button>Click me</Button>)
    expect(screen.getByRole('button', { name: 'Click me' })).toBeInTheDocument()
  })

  it('fires onClick when clicked', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<Button onClick={onClick}>Go</Button>)
    await user.click(screen.getByRole('button'))
    expect(onClick).toHaveBeenCalledTimes(1)
  })

  it('is disabled when disabled prop is set', () => {
    render(<Button disabled>Disabled</Button>)
    expect(screen.getByRole('button')).toBeDisabled()
  })

  it('does not fire onClick when disabled', async () => {
    const user = userEvent.setup()
    const onClick = vi.fn()
    render(<Button disabled onClick={onClick}>Disabled</Button>)
    await user.click(screen.getByRole('button'))
    expect(onClick).not.toHaveBeenCalled()
  })

  it('applies variant class', () => {
    render(<Button variant="danger">Danger</Button>)
    const btn = screen.getByRole('button')
    expect(btn.className).toMatch(/rose/)
  })

  it('applies size class', () => {
    render(<Button size="sm">Small</Button>)
    const btn = screen.getByRole('button')
    expect(btn.className).toMatch(/h-8/)
  })

  it('forwards extra props', () => {
    render(<Button data-testid="my-btn">Test</Button>)
    expect(screen.getByTestId('my-btn')).toBeInTheDocument()
  })
})

// ---------------------------------------------------------------------------
// Badge
// ---------------------------------------------------------------------------
describe('Badge', () => {
  it('renders children', () => {
    render(<Badge>New</Badge>)
    expect(screen.getByText('New')).toBeInTheDocument()
  })

  it('default variant has violet classes', () => {
    render(<Badge variant="default">Default</Badge>)
    expect(screen.getByText('Default').className).toMatch(/violet/)
  })

  it('success variant has emerald classes', () => {
    render(<Badge variant="success">OK</Badge>)
    expect(screen.getByText('OK').className).toMatch(/emerald/)
  })

  it('danger variant has rose classes', () => {
    render(<Badge variant="danger">Error</Badge>)
    expect(screen.getByText('Error').className).toMatch(/rose/)
  })

  it('warning variant has amber classes', () => {
    render(<Badge variant="warning">Warn</Badge>)
    expect(screen.getByText('Warn').className).toMatch(/amber/)
  })

  it('muted variant has zinc classes', () => {
    render(<Badge variant="muted">Muted</Badge>)
    expect(screen.getByText('Muted').className).toMatch(/zinc/)
  })

  it('accepts extra className', () => {
    render(<Badge className="extra-class">Tag</Badge>)
    expect(screen.getByText('Tag').className).toMatch(/extra-class/)
  })
})

// ---------------------------------------------------------------------------
// Input
// ---------------------------------------------------------------------------
describe('Input', () => {
  it('renders an input element', () => {
    render(<Input />)
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('displays the value prop', () => {
    render(<Input value="hello" onChange={() => {}} />)
    expect(screen.getByRole('textbox')).toHaveValue('hello')
  })

  it('calls onChange when typed into', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Input value="" onChange={onChange} />)
    await user.type(screen.getByRole('textbox'), 'a')
    expect(onChange).toHaveBeenCalled()
  })

  it('renders placeholder text', () => {
    render(<Input placeholder="Enter name" />)
    expect(screen.getByPlaceholderText('Enter name')).toBeInTheDocument()
  })

  it('passes type prop through', () => {
    render(<Input type="email" />)
    expect(screen.getByRole('textbox')).toHaveAttribute('type', 'email')
  })
})

// ---------------------------------------------------------------------------
// Textarea
// ---------------------------------------------------------------------------
describe('Textarea', () => {
  it('renders a textarea element', () => {
    render(<Textarea />)
    expect(screen.getByRole('textbox')).toBeInTheDocument()
  })

  it('displays the value prop', () => {
    render(<Textarea value="some text" onChange={() => {}} />)
    expect(screen.getByRole('textbox')).toHaveValue('some text')
  })

  it('calls onChange when user types', async () => {
    const user = userEvent.setup()
    const onChange = vi.fn()
    render(<Textarea value="" onChange={onChange} />)
    await user.type(screen.getByRole('textbox'), 'hi')
    expect(onChange).toHaveBeenCalled()
  })

  it('accepts rows prop', () => {
    render(<Textarea rows={5} />)
    expect(screen.getByRole('textbox')).toHaveAttribute('rows', '5')
  })
})

// ---------------------------------------------------------------------------
// Switch
// ---------------------------------------------------------------------------
describe('Switch', () => {
  it('renders as a button', () => {
    render(<Switch checked={false} onCheckedChange={() => {}} />)
    expect(screen.getByRole('button')).toBeInTheDocument()
  })

  it('renders with a label when label prop is provided', () => {
    render(<Switch checked={false} onCheckedChange={() => {}} label="Enable" />)
    expect(screen.getByText('Enable')).toBeInTheDocument()
  })

  it('does not render label text when label is not provided', () => {
    const { container } = render(<Switch checked={false} onCheckedChange={() => {}} />)
    // No extra text nodes — just the button with its nested spans
    expect(container.querySelectorAll('span').length).toBe(2)
  })

  it('calls onCheckedChange with toggled value when clicked', async () => {
    const user = userEvent.setup()
    const onCheckedChange = vi.fn()
    render(<Switch checked={false} onCheckedChange={onCheckedChange} />)
    await user.click(screen.getByRole('button'))
    expect(onCheckedChange).toHaveBeenCalledWith(true)
  })

  it('calls onCheckedChange with false when checked is true', async () => {
    const user = userEvent.setup()
    const onCheckedChange = vi.fn()
    render(<Switch checked={true} onCheckedChange={onCheckedChange} />)
    await user.click(screen.getByRole('button'))
    expect(onCheckedChange).toHaveBeenCalledWith(false)
  })

  it('checked state applies emerald classes to the track', () => {
    render(<Switch checked={true} onCheckedChange={() => {}} />)
    const trackSpan = screen.getByRole('button').querySelector('span')
    expect(trackSpan.className).toMatch(/emerald/)
  })

  it('unchecked state does not apply violet track classes', () => {
    render(<Switch checked={false} onCheckedChange={() => {}} />)
    const trackSpan = screen.getByRole('button').querySelector('span')
    expect(trackSpan.className).not.toMatch(/violet-500/)
  })
})

// ---------------------------------------------------------------------------
// Select
// ---------------------------------------------------------------------------
describe('Select', () => {
  const options = [
    { value: 'a', label: 'Option A' },
    { value: 'b', label: 'Option B' },
  ]

  it('renders a trigger button', () => {
    render(<Select value="" onValueChange={() => {}} options={options} />)
    // Radix Select renders a button role trigger
    expect(screen.getByRole('combobox')).toBeInTheDocument()
  })

  it('shows placeholder when no value selected', () => {
    render(<Select value="" onValueChange={() => {}} options={options} placeholder="Pick one" />)
    expect(screen.getByText('Pick one')).toBeInTheDocument()
  })

  it('shows selected value label', () => {
    render(<Select value="a" onValueChange={() => {}} options={options} />)
    expect(screen.getByRole('combobox')).toHaveTextContent('Option A')
  })

  it('opens dropdown and shows options on click', async () => {
    const user = userEvent.setup()
    render(<Select value="" onValueChange={() => {}} options={options} />)
    await user.click(screen.getByRole('combobox'))
    expect(screen.getByText('Option A')).toBeInTheDocument()
    expect(screen.getByText('Option B')).toBeInTheDocument()
  })

  it('calls onValueChange when an option is selected', async () => {
    const user = userEvent.setup()
    const onValueChange = vi.fn()
    render(<Select value="" onValueChange={onValueChange} options={options} />)
    await user.click(screen.getByRole('combobox'))
    await user.click(screen.getByText('Option A'))
    expect(onValueChange).toHaveBeenCalledWith('a')
  })
})

// ---------------------------------------------------------------------------
// Card
// ---------------------------------------------------------------------------
describe('Card', () => {
  it('renders children inside a div', () => {
    render(<Card>Content</Card>)
    expect(screen.getByText('Content')).toBeInTheDocument()
  })

  it('accepts extra className', () => {
    const { container } = render(<Card className="my-card">Content</Card>)
    expect(container.firstChild.className).toMatch(/my-card/)
  })
})
