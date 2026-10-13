import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const badgeVariants = cva(
  "inline-flex items-center rounded-md border px-2 py-0.5 text-xs font-semibold transition-colors",
  {
    variants: {
      variant: {
        default: "border-transparent bg-[var(--magenta-soft)] text-[var(--magenta)]",
        secondary: "border-[var(--border)] bg-[var(--bg)] text-[var(--text-dim)]",
        high: "border-transparent bg-[#fde8ed] text-[#c53050]",
        medium: "border-transparent bg-[#fef3e2] text-[#b7791f]",
        low: "border-transparent bg-[#e6f6ee] text-[#1f8a5b]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLDivElement>,
    VariantProps<typeof badgeVariants> {}

function Badge({ className, variant, ...props }: BadgeProps) {
  return <div className={cn(badgeVariants({ variant }), className)} {...props} />;
}

export { Badge, badgeVariants };
