"use client";

import { useMemo, useState } from "react";
import type { ColumnDef } from "@tanstack/react-table";
import { Users, Plus, Lock } from "lucide-react";
import { Panel, PanelHeader, PanelSection } from "@/components/ui/Panel";
import { MicroLabel } from "@/components/ui/MicroLabel";
import { DataTable } from "@/components/ui/DataTable";
import { Button } from "@/components/ui/Button";
import { EmptyState } from "@/components/ui/EmptyState";
import { Field } from "@/components/ui/Field";
import { Input } from "@/components/ui/Input";
import { Select } from "@/components/ui/Select";
import { Drawer } from "@/components/ui/Drawer";
import { useToast } from "@/components/ui/Toast";
import { useUsers, useInviteUser, usePatchUser } from "@/lib/api/hooks";
import { useSession } from "@/lib/auth/session";
import { formatDate } from "@/lib/format";
import type { User, UserRole } from "@/lib/api/schema";

const ROLE_OPTIONS = [
  { value: "admin", label: "Admin" },
  { value: "sales_manager", label: "Sales Manager" },
  { value: "sales_executive", label: "Sales Executive" },
  { value: "viewer", label: "Viewer" },
];

const ROLE_LABEL: Record<string, string> = {
  admin: "Admin",
  sales_manager: "Sales Manager",
  sales_executive: "Sales Executive",
  viewer: "Viewer",
};

export default function UsersSettingsPage() {
  const { data: users = [], isLoading } = useUsers();
  const invite = useInviteUser();
  const patch = usePatchUser();
  const { can, user: me } = useSession();
  const { toast } = useToast();
  const canManage = can("users.manage");

  const [open, setOpen] = useState(false);
  const [email, setEmail] = useState("");
  const [name, setName] = useState("");
  const [role, setRole] = useState<UserRole>("sales_executive");

  async function handleInvite() {
    if (!email.trim()) {
      toast({ tone: "warn", title: "Email required" });
      return;
    }
    try {
      await invite.mutateAsync({ email: email.trim(), name: name.trim() || undefined, role });
      toast({ tone: "success", title: "Invitation sent", description: email.trim() });
      setOpen(false);
      setEmail("");
      setName("");
      setRole("sales_executive");
    } catch (e) {
      toast({ tone: "error", title: "Invite failed", description: (e as Error).message });
    }
  }

  async function changeRole(u: User, next: UserRole) {
    if (next === u.role) return;
    try {
      await patch.mutateAsync({ id: u.id, patch: { role: next } });
      toast({ tone: "success", title: `Role updated`, description: `${u.email} → ${ROLE_LABEL[next]}` });
    } catch (e) {
      toast({ tone: "error", title: "Update failed", description: (e as Error).message });
    }
  }

  const columns = useMemo<ColumnDef<User, unknown>[]>(
    () => [
      {
        accessorKey: "name",
        header: "Name",
        cell: (c) => {
          const u = c.row.original;
          return (
            <div className="flex flex-col">
              <span className="text-sm font-medium text-ink">
                {u.name || "—"}
                {me?.id === u.id ? <span className="ml-1 text-[10px] text-accent">(you)</span> : null}
              </span>
            </div>
          );
        },
      },
      {
        accessorKey: "email",
        header: "Email",
        cell: (c) => <span className="font-mono text-xs text-muted">{String(c.getValue())}</span>,
        meta: { mono: true, mobilePriority: "medium" },
      },
      {
        accessorKey: "role",
        header: "Role",
        cell: (c) => {
          const u = c.row.original;
          if (!canManage) {
            return <span className="text-sm text-ink">{ROLE_LABEL[u.role] ?? u.role}</span>;
          }
          return (
            <Select
              className="h-8 max-w-[180px] text-xs"
              options={ROLE_OPTIONS}
              value={u.role}
              disabled={patch.isPending}
              onChange={(e) => changeRole(u, e.target.value as UserRole)}
            />
          );
        },
      },
      {
        accessorKey: "created_at",
        header: "Joined",
        cell: (c) => (
          <span className="text-xs text-muted">{formatDate(c.getValue() as string | undefined)}</span>
        ),
        meta: { mobilePriority: "low" },
      },
    ],
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [canManage, patch.isPending, me?.id],
  );

  return (
    <Panel flush>
      <PanelHeader
        className="px-4 pt-4 sm:px-5"
        actions={
          canManage ? (
            <Button size="sm" onClick={() => setOpen(true)}>
              <Plus className="size-4" /> Invite user
            </Button>
          ) : (
            <span className="flex items-center gap-1 text-xs text-muted">
              <Lock className="size-3.5" /> Admin only
            </span>
          )
        }
      >
        <MicroLabel className="text-accent/70">Settings</MicroLabel>
        <h2 className="text-base font-semibold text-ink">Users & Roles</h2>
      </PanelHeader>

      <DataTable<User>
        columns={columns}
        data={users}
        loading={isLoading}
        getRowId={(r) => r.id}
        emptyState={
          <EmptyState
            icon={Users}
            kicker="No members"
            title="No users found"
            description="Invite teammates and assign RBAC roles: Admin, Sales Manager, Sales Executive, or Viewer."
            action={
              canManage ? (
                <Button size="sm" onClick={() => setOpen(true)}>
                  <Plus className="size-4" /> Invite user
                </Button>
              ) : null
            }
          />
        }
      />

      <PanelSection className="px-4 sm:px-5">
        <div className="grid grid-cols-1 gap-2 text-xs text-muted sm:grid-cols-2 lg:grid-cols-4">
          <p><span className="text-ink">Admin</span> — everything</p>
          <p><span className="text-ink">Sales Manager</span> — jobs, campaigns, sheets, exports, metrics</p>
          <p><span className="text-ink">Sales Executive</span> — assigned leads, campaigns, dispositions</p>
          <p><span className="text-ink">Viewer</span> — read-only dashboard & reports</p>
        </div>
      </PanelSection>

      <Drawer open={open} onOpenChange={setOpen}>
        <Drawer.Content title="Invite user" kicker="Users & Roles" width="sm">
          <div className="flex flex-col gap-4">
            <Field label="Email" required>
              <Input
                type="email"
                placeholder="teammate@company.com"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
              />
            </Field>
            <Field label="Name" hint="Optional — shown in the members table.">
              <Input placeholder="Jane Doe" value={name} onChange={(e) => setName(e.target.value)} />
            </Field>
            <Field label="Role">
              <Select
                options={ROLE_OPTIONS}
                value={role}
                onChange={(e) => setRole(e.target.value as UserRole)}
              />
            </Field>
            <div className="flex justify-end gap-2 pt-2">
              <Button variant="ghost" size="sm" onClick={() => setOpen(false)}>
                Cancel
              </Button>
              <Button size="sm" onClick={handleInvite} disabled={invite.isPending}>
                {invite.isPending ? "Sending…" : "Send invite"}
              </Button>
            </div>
          </div>
        </Drawer.Content>
      </Drawer>
    </Panel>
  );
}
