"use client";

import * as React from "react";
import { useRouter } from "next/navigation";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui/card";
import { Field, FieldGroup, FieldLabel } from "@/components/ui/field";
import { Input } from "@/components/ui/input";
import { Alert, AlertDescription, AlertTitle } from "@/components/ui/alert";
import { Spinner } from "@/components/ui/spinner";
import { AlertCircle } from "lucide-react";
import { login as loginApi } from "@/lib/api/auth";
import { setToken } from "@/lib/api/token";

// Adapted from the shadcn login-01 block: dopilot uses a single admin
// username/password (no email / social / signup / forgot-password).
export function LoginForm({ className, ...props }: React.ComponentProps<"div">) {
  const { t } = useTranslation();
  const router = useRouter();
  const [username, setUsername] = React.useState("");
  const [password, setPassword] = React.useState("");
  const [loading, setLoading] = React.useState(false);
  const [errorMsg, setErrorMsg] = React.useState("");

  async function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    setErrorMsg("");
    setLoading(true);
    try {
      const res = await loginApi(username, password);
      if (res.access_token) {
        setToken(res.access_token);
      }
      router.replace("/dashboard");
    } catch {
      setErrorMsg(t("login.error"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <div className={cn("flex flex-col gap-6", className)} {...props}>
      <Card>
        <CardHeader>
          <CardTitle>{t("login.title")}</CardTitle>
          <CardDescription>{t("login.subtitle")}</CardDescription>
        </CardHeader>
        <CardContent>
          <form onSubmit={onSubmit}>
            <FieldGroup>
              <Field>
                <FieldLabel htmlFor="username">
                  {t("login.username")}
                </FieldLabel>
                <Input
                  id="username"
                  data-testid="login-username"
                  autoComplete="username"
                  value={username}
                  onChange={(e) => setUsername(e.target.value)}
                />
              </Field>
              <Field>
                <FieldLabel htmlFor="password">
                  {t("login.password")}
                </FieldLabel>
                <Input
                  id="password"
                  type="password"
                  data-testid="login-password"
                  autoComplete="current-password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                />
              </Field>
              {errorMsg && (
                <Alert variant="destructive" data-testid="login-error">
                  <AlertCircle />
                  <AlertTitle>{errorMsg}</AlertTitle>
                  <AlertDescription className="sr-only">
                    {errorMsg}
                  </AlertDescription>
                </Alert>
              )}
              <Field>
                <Button
                  type="submit"
                  data-testid="login-submit"
                  disabled={loading}
                >
                  {loading && <Spinner data-icon="inline-start" />}
                  {t("login.submit")}
                </Button>
              </Field>
            </FieldGroup>
          </form>
        </CardContent>
      </Card>
    </div>
  );
}
