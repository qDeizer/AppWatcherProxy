import type { ButtonHTMLAttributes, ReactNode } from 'react'

interface IconButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  icon: ReactNode
  label: string
  variant?: 'primary' | 'danger' | 'neutral'
}

export function IconButton({ icon, label, variant = 'neutral', className = '', ...props }: IconButtonProps) {
  return (
    <button className={`button button-${variant} ${className}`} {...props}>
      {icon}
      <span>{label}</span>
    </button>
  )
}

