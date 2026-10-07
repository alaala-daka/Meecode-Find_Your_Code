export function LoginDeniedPage() {
  return (
    <main className="flex min-h-screen items-center justify-center bg-paper px-6">
      <section className="w-full max-w-sm rounded-lg border border-line bg-surface p-8 text-center">
        <h1 className="font-mono text-xl text-ink">无管理权限</h1>
        <p className="mt-3 text-sm text-ink-2">
          当前 GitHub 账号不在管理台白名单内，请联系管理员开通后再访问。
        </p>
        <a
          href="/"
          className="mt-6 inline-flex h-9 items-center rounded-md border border-line px-4 text-sm text-ink-2 transition-colors duration-[180ms] hover:border-line-strong hover:text-ink"
        >
          返回主站
        </a>
      </section>
    </main>
  );
}

export default LoginDeniedPage;
