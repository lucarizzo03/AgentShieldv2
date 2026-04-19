export default function ToastStack({ toasts }) {
  return (
    <div className="pointer-events-none fixed right-6 top-6 z-50 flex w-[360px] flex-col gap-2">
      {toasts.map((toast) => (
        <div
          key={toast.id}
          className={`rounded-md border px-4 py-3 text-sm shadow-lg ${
            toast.type === "success"
              ? "border-emerald/40 bg-emerald/10 text-emerald"
              : "border-rose/40 bg-rose/10 text-rose"
          }`}
        >
          {toast.message}
        </div>
      ))}
    </div>
  );
}

