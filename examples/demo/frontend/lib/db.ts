import { OrderState } from "./orderState";
import { UserStatus } from "./userStatus";

export type Role = "admin" | "manager" | "viewer";

export interface User {
  id: string;
  status: UserStatus;
  role: Role;
  region: "eu" | "us" | "apac";
  riskScore: number;
}

export interface Order {
  id: string;
  state: OrderState;
  ownerId: string;
  totalCents: number;
  expedited: boolean;
}

export interface AuditEvent {
  actorId: string;
  action: string;
  reason?: string;
}

interface Table<T> {
  find(request: Request): Promise<T>;
  save(value: T): Promise<T>;
}

export const database: {
  users: Table<User>;
  orders: Table<Order>;
  audit: {
    write(event: AuditEvent): Promise<void>;
  };
} = {
  users: {
    find: async () => ({
      id: "1",
      status: UserStatus.ACTIVE,
      role: "manager",
      region: "eu",
      riskScore: 12,
    }),
    save: async user => user,
  },
  orders: {
    find: async () => ({
      id: "1",
      state: OrderState.OPEN,
      ownerId: "1",
      totalCents: 12900,
      expedited: false,
    }),
    save: async order => order,
  },
  audit: {
    write: async () => undefined,
  },
};
