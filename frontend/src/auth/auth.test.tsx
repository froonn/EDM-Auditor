import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AuthProvider, useAuth } from "./AuthProvider";
import { Can } from "./Can";
import { PERMISSIONS } from "./permissions";
import { LOCAL_SESSION, sessionWith } from "./session";

function UserName() {
  return <span>{useAuth().session.user?.name ?? "anonymous"}</span>;
}

describe("authorization", () => {
  it("grants every permission to the local session", () => {
    expect([...LOCAL_SESSION.permissions].sort()).toEqual([...PERMISSIONS].sort());
    expect(LOCAL_SESSION.user).toBeNull();
  });

  it("shows actions only with the permission", () => {
    render(
      <AuthProvider session={sessionWith(["audit.run"], { id: 7, name: "auditor" })}>
        <Can permission="audit.run">
          <span>run</span>
        </Can>
        <Can permission="rules.edit" fallback={<span>read only</span>}>
          <span>edit</span>
        </Can>
        <UserName />
      </AuthProvider>,
    );
    expect(screen.getByText("run")).toBeInTheDocument();
    expect(screen.queryByText("edit")).not.toBeInTheDocument();
    expect(screen.getByText("read only")).toBeInTheDocument();
    expect(screen.getByText("auditor")).toBeInTheDocument();
  });

  it("requires the provider", () => {
    expect(() => render(<UserName />)).toThrow("useAuth must be used inside AuthProvider");
  });
});
