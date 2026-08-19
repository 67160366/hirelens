import type { ButtonHTMLAttributes, ReactNode } from "react";

import { cn } from "@/lib/cn";

/**
 * One button, four intents.
 *
 * The tree grew 14 distinct button recipes for five intents, and exactly one of
 * them carried a real focus indicator. Routing them through here is what makes the
 * focus ring, the disabled state and the press response impossible to forget.
 *
 * `type` defaults to "button": every one of these lives inside a form somewhere,
 * and a button that submits by accident is a request nobody asked for.
 */
export function Button({
  variant = "secondary",
  size = "sm",
  className,
  children,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: "primary" | "secondary" | "ghost" | "danger";
  size?: "sm" | "lg";
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      {...rest}
      className={cn(
        variant === "primary" && "btn-primary",
        variant === "secondary" && "btn-secondary",
        variant === "ghost" && "btn-ghost",
        // Destructive actions are the one place the meaning palette is borrowed for
        // a control, and only because refusing a claim and destroying a row are the
        // same red to a reader: this cannot be undone.
        variant === "danger" &&
          "btn border border-dropped/40 bg-dropped-wash text-dropped hover:bg-dropped hover:text-on-accent",
        size === "lg" && "btn-lg",
        "ring-focus",
        className,
      )}
    >
      {children}
    </button>
  );
}
