import { clsx } from "clsx"
import { twMerge } from "tailwind-merge"

export function cn(...inputs) {
  return twMerge(clsx(inputs))
}

export function formatTime(value) {
  const seconds = Number(value || 0)
  const minutes = Math.floor(seconds / 60)
  const rest = Math.floor(seconds % 60)
  return `${minutes}:${String(rest).padStart(2, "0")}`
}

export function mediaUrl(path, version = "") {
  return path ? `/api/media?path=${encodeURIComponent(path)}${version ? `&v=${encodeURIComponent(version)}` : ""}` : ""
}
