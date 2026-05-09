/**
 * Mock data for TaskDetailPage (PR6 / R4.4).
 *
 * Provides a single demo task with modules, findings, and timeline events.
 * Deterministic — no random — so tests and screenshots stay stable.
 */

// ─── Task Status ──────────────────────────────────────────────────────────────

export type TaskStatus =
  | "queued"
  | "running"
  | "awaiting_user"
  | "completed"
  | "failed"
  | "cancelled"
  | "paused";

export interface TaskModule {
  name: string;
  agent: string;
  status: TaskStatus;
  startedAt: string;
  endedAt?: string;
  findingsCount: number;
}

export interface TaskFinding {
  id: string;
  title: string;
  severity: "critical" | "high" | "medium" | "low";
  category: "cve" | "weak_password" | "misconfig" | "exposure";
  target: string;
  foundAt: string;
}

export interface TaskInfo {
  id: string;
  title: string;
  status: TaskStatus;
  target: string;
  createdAt: string;
  startedAt: string;
  completedAt?: string;
  duration: string;
  totalFindings: number;
  criticalCount: number;
  highCount: number;
  agentsUsed: number;
  modules: TaskModule[];
  findings: TaskFinding[];
}

// ─── Demo Task ────────────────────────────────────────────────────────────────

export const demoTask: TaskInfo = {
  id: "demo",
  title: "生产环境全面安全评估",
  status: "completed",
  target: "10.0.0.0/16 + *.internal.corp",
  createdAt: "2026-05-09 09:00:00",
  startedAt: "2026-05-09 09:00:12",
  completedAt: "2026-05-09 10:47:33",
  duration: "1h 47m 21s",
  totalFindings: 23,
  criticalCount: 3,
  highCount: 8,
  agentsUsed: 4,
  modules: [
    {
      name: "资产发现",
      agent: "asset_discovery",
      status: "completed",
      startedAt: "09:00:12",
      endedAt: "09:12:45",
      findingsCount: 0,
    },
    {
      name: "端口扫描",
      agent: "port_scan",
      status: "completed",
      startedAt: "09:12:46",
      endedAt: "09:28:03",
      findingsCount: 4,
    },
    {
      name: "漏洞扫描",
      agent: "vuln_scan",
      status: "completed",
      startedAt: "09:28:04",
      endedAt: "10:15:22",
      findingsCount: 14,
    },
    {
      name: "弱口令检测",
      agent: "weak_password",
      status: "completed",
      startedAt: "10:15:23",
      endedAt: "10:42:18",
      findingsCount: 5,
    },
  ],
  findings: [
    {
      id: "f-001",
      title: "Apache Struts2 远程代码执行 (CVE-2024-53677)",
      severity: "critical",
      category: "cve",
      target: "10.0.1.15:8080",
      foundAt: "09:45:12",
    },
    {
      id: "f-002",
      title: "MySQL root 空密码",
      severity: "critical",
      category: "weak_password",
      target: "10.0.3.21:3306",
      foundAt: "10:22:08",
    },
    {
      id: "f-003",
      title: "Kubernetes API Server 未鉴权",
      severity: "critical",
      category: "misconfig",
      target: "10.0.0.5:6443",
      foundAt: "09:55:33",
    },
    {
      id: "f-004",
      title: "Redis 弱口令 (123456)",
      severity: "high",
      category: "weak_password",
      target: "10.0.3.22:6379",
      foundAt: "10:25:14",
    },
    {
      id: "f-005",
      title: "Jenkins 匿名读取权限",
      severity: "high",
      category: "misconfig",
      target: "ci.internal.corp:8080",
      foundAt: "09:52:41",
    },
    {
      id: "f-006",
      title: "Nginx 版本泄露",
      severity: "medium",
      category: "exposure",
      target: "web.internal.corp:443",
      foundAt: "09:35:18",
    },
    {
      id: "f-007",
      title: "SSH 弱密码策略",
      severity: "medium",
      category: "weak_password",
      target: "10.0.2.100:22",
      foundAt: "10:31:55",
    },
    {
      id: "f-008",
      title: "CORS 配置过于宽松",
      severity: "low",
      category: "misconfig",
      target: "api.internal.corp",
      foundAt: "09:48:27",
    },
  ],
};
