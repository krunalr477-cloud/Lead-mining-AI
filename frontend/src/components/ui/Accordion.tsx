"use client";

import { Accordion as RadixAccordion } from "radix-ui";
import { ChevronDown } from "lucide-react";
import { cn } from "@/lib/cn";

/**
 * Accordion — thin wrapper over Radix Accordion with the LeadMine dark
 * treatment. Each item is a border-divided row with a chevron that rotates on
 * open. Compose:
 *   <Accordion type="multiple">
 *     <AccordionItem value="x">
 *       <AccordionTrigger>Question</AccordionTrigger>
 *       <AccordionContent>Answer</AccordionContent>
 *     </AccordionItem>
 *   </Accordion>
 */
export const Accordion = RadixAccordion.Root;

export function AccordionItem({ className, ...props }: RadixAccordion.AccordionItemProps) {
  return (
    <RadixAccordion.Item
      className={cn("border-b border-border last:border-b-0", className)}
      {...props}
    />
  );
}

export function AccordionTrigger({
  className,
  children,
  ...props
}: RadixAccordion.AccordionTriggerProps) {
  return (
    <RadixAccordion.Header className="flex">
      <RadixAccordion.Trigger
        className={cn(
          "group flex flex-1 items-center justify-between gap-3 py-3 text-left text-sm font-medium text-ink transition-colors lm-focus",
          "hover:text-accent",
          className,
        )}
        {...props}
      >
        {children}
        <ChevronDown
          className="size-4 shrink-0 text-muted transition-transform duration-200 group-data-[state=open]:rotate-180 group-hover:text-accent"
          aria-hidden
        />
      </RadixAccordion.Trigger>
    </RadixAccordion.Header>
  );
}

export function AccordionContent({
  className,
  children,
  ...props
}: RadixAccordion.AccordionContentProps) {
  return (
    <RadixAccordion.Content
      className={cn(
        "overflow-hidden text-sm text-muted",
        "data-[state=open]:animate-[accordion-down_200ms_ease-out] data-[state=closed]:animate-[accordion-up_180ms_ease-in]",
        className,
      )}
      {...props}
    >
      <div className="pb-4 pt-0 leading-relaxed">{children}</div>
    </RadixAccordion.Content>
  );
}
