import Link from "next/link";
import Head from "next/head";

export default function Custom500() {
  return (
    <>
      <Head>
        <title>500 - Server Error | Alex AI Financial Advisor</title>
      </Head>

      <div className="min-h-screen bg-background flex items-center justify-center px-4">
        <div className="text-center">
          <h1 className="text-6xl font-bold text-error mb-4">500</h1>
          <h2 className="text-2xl font-semibold text-foreground mb-4">
            Internal Server Error
          </h2>
          <p className="text-muted mb-8">
            Something went wrong on our end. Please try again later.
          </p>
          <Link href="/dashboard">
            <button className="bg-primary hover:bg-primary/90 text-white px-6 py-3 rounded-lg transition-colors">
              Return to Dashboard
            </button>
          </Link>
        </div>
      </div>
    </>
  );
}
