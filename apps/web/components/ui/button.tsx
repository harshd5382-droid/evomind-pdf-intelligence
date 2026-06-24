import { ButtonHTMLAttributes, forwardRef } from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-1.5 font-medium transition-all duration-150 disabled:opacity-40 disabled:cursor-not-allowed select-none",
  {
    variants: {
      variant: {
        primary: [
          "bg-accent text-bg font-semibold",
          "hover:bg-accent/90 shadow-soft",
          "active:scale-[0.98]",
        ],
        ghost: [
          "bg-transparent text-sub border border-border",
          "hover:text-ink hover:border-accent/40",
          "active:scale-[0.98]",
        ],
        outline: [
          "border border-border text-ink",
          "hover:border-accent/40 hover:bg-white/[0.03]",
          "active:scale-[0.98]",
        ],
      },
      size: {
        sm: "h-7 px-2.5 text-[11px] tracking-wide",
        md: "h-8 px-3.5 text-[12.5px]",
        lg: "h-10 px-5 text-sm",
      },
    },
    defaultVariants: { variant: "primary", size: "md" },
  },
);

export interface ButtonProps
  extends ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {}

export const Button = forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => (
    <button
      ref={ref}
      className={cn(buttonVariants({ variant, size }), className)}
      {...props}
    />
  ),
);
Button.displayName = "Button";
