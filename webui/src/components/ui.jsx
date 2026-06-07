import * as DialogPrimitive from "@radix-ui/react-dialog"
import * as SelectPrimitive from "@radix-ui/react-select"
import * as TabsPrimitive from "@radix-ui/react-tabs"
import { Check, ChevronDown, X } from "lucide-react"
import { forwardRef } from "react"
import { cn } from "../lib/utils"

export const Button = forwardRef(function Button(
  { className, variant = "default", size = "default", ...props },
  ref,
) {
  const variants = {
    default: "bg-primary text-primary-foreground hover:bg-violet-500 shadow-lg shadow-violet-950/20",
    secondary: "bg-white/[0.07] text-zinc-100 hover:bg-white/[0.12] border border-white/10",
    ghost: "text-zinc-400 hover:bg-white/[0.07] hover:text-white",
    danger: "bg-rose-500/15 text-rose-300 hover:bg-rose-500/25 border border-rose-400/20",
    success: "bg-emerald-500/15 text-emerald-300 hover:bg-emerald-500/25 border border-emerald-400/20",
  }
  const sizes = {
    default: "h-10 px-4 py-2",
    sm: "h-8 rounded-lg px-3 text-xs",
    icon: "h-9 w-9",
    lg: "h-12 rounded-xl px-6",
  }
  return (
    <button
      ref={ref}
      className={cn(
        "inline-flex items-center justify-center gap-2 rounded-xl text-sm font-medium transition-all focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-violet-400 disabled:pointer-events-none disabled:opacity-40",
        variants[variant],
        sizes[size],
        className,
      )}
      {...props}
    />
  )
})

export function Card({ className, ...props }) {
  return <div className={cn("rounded-2xl border border-white/[0.08] bg-card/85 shadow-xl shadow-black/10 backdrop-blur-xl", className)} {...props} />
}

export const Input = forwardRef(function Input({ className, ...props }, ref) {
  return <input ref={ref} className={cn("h-10 w-full rounded-xl border border-white/10 bg-black/20 px-3 text-sm text-zinc-100 outline-none transition placeholder:text-zinc-600 focus:border-violet-400/60 focus:ring-2 focus:ring-violet-500/15", className)} {...props} />
})

export const Textarea = forwardRef(function Textarea({ className, ...props }, ref) {
  return <textarea ref={ref} className={cn("min-h-28 w-full resize-none rounded-xl border border-white/10 bg-black/20 px-4 py-3 text-sm leading-6 text-zinc-100 outline-none transition placeholder:text-zinc-600 focus:border-violet-400/60 focus:ring-2 focus:ring-violet-500/15", className)} {...props} />
})

export function Badge({ className, variant = "default", ...props }) {
  const variants = {
    default: "border-violet-400/20 bg-violet-400/10 text-violet-300",
    muted: "border-white/10 bg-white/5 text-zinc-400",
    success: "border-emerald-400/20 bg-emerald-400/10 text-emerald-300",
    warning: "border-amber-400/20 bg-amber-400/10 text-amber-300",
    danger: "border-rose-400/20 bg-rose-400/10 text-rose-300",
  }
  return <span className={cn("inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-medium", variants[variant], className)} {...props} />
}

export const Tabs = TabsPrimitive.Root
export const TabsList = ({ className, ...props }) => <TabsPrimitive.List className={cn("inline-flex rounded-xl border border-white/10 bg-black/20 p-1", className)} {...props} />
export const TabsTrigger = ({ className, ...props }) => <TabsPrimitive.Trigger className={cn("rounded-lg px-4 py-2 text-sm text-zinc-500 transition data-[state=active]:bg-white/10 data-[state=active]:text-white data-[state=active]:shadow-sm", className)} {...props} />
export const TabsContent = ({ className, ...props }) => <TabsPrimitive.Content className={cn("mt-4 outline-none", className)} {...props} />

export const Dialog = DialogPrimitive.Root
export const DialogTrigger = DialogPrimitive.Trigger
export const DialogClose = DialogPrimitive.Close
export function DialogContent({ className, children, ...props }) {
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm" />
      <DialogPrimitive.Content className={cn("fixed left-1/2 top-1/2 z-50 max-h-[92vh] w-[calc(100%-2rem)] max-w-3xl -translate-x-1/2 -translate-y-1/2 overflow-auto rounded-2xl border border-white/10 bg-zinc-950 p-6 text-zinc-100 shadow-2xl", className)} {...props}>
        {children}
        <DialogPrimitive.Close className="absolute right-4 top-4 rounded-lg p-2 text-zinc-500 hover:bg-white/10 hover:text-white"><X className="h-4 w-4" /></DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
  )
}
export const DialogTitle = ({ className, ...props }) => <DialogPrimitive.Title className={cn("text-lg font-semibold", className)} {...props} />
export const DialogDescription = ({ className, ...props }) => <DialogPrimitive.Description className={cn("mt-1 text-sm text-zinc-500", className)} {...props} />

export function Select({ value, onValueChange, options, placeholder = "Chon" }) {
  return (
    <SelectPrimitive.Root value={value} onValueChange={onValueChange}>
      <SelectPrimitive.Trigger className="flex h-10 w-full items-center justify-between rounded-xl border border-white/10 bg-black/20 px-3 text-sm text-zinc-200 outline-none focus:border-violet-400/60">
        <SelectPrimitive.Value placeholder={placeholder} />
        <SelectPrimitive.Icon><ChevronDown className="h-4 w-4 text-zinc-500" /></SelectPrimitive.Icon>
      </SelectPrimitive.Trigger>
      <SelectPrimitive.Portal>
        <SelectPrimitive.Content position="popper" className="z-[70] min-w-[var(--radix-select-trigger-width)] overflow-hidden rounded-xl border border-white/10 bg-zinc-900 p-1 text-zinc-200 shadow-2xl">
          <SelectPrimitive.Viewport>
            {options.map((option) => (
              <SelectPrimitive.Item key={option.value} value={option.value} className="relative flex cursor-pointer select-none items-center rounded-lg py-2 pl-8 pr-3 text-sm outline-none data-[highlighted]:bg-white/10">
                <SelectPrimitive.ItemIndicator className="absolute left-2"><Check className="h-4 w-4" /></SelectPrimitive.ItemIndicator>
                <SelectPrimitive.ItemText>{option.label}</SelectPrimitive.ItemText>
              </SelectPrimitive.Item>
            ))}
          </SelectPrimitive.Viewport>
        </SelectPrimitive.Content>
      </SelectPrimitive.Portal>
    </SelectPrimitive.Root>
  )
}

export function Switch({ checked, onCheckedChange, label }) {
  return (
    <button type="button" onClick={() => onCheckedChange(!checked)} className="flex items-center gap-2 text-sm text-zinc-300">
      <span className={cn("relative h-6 w-11 rounded-full border transition", checked ? "border-violet-400/40 bg-violet-500" : "border-white/10 bg-white/10")}>
        <span className={cn("absolute top-0.5 h-4.5 w-4.5 rounded-full bg-white shadow transition-all", checked ? "left-[21px]" : "left-0.5")} />
      </span>
      {label && <span>{label}</span>}
    </button>
  )
}
