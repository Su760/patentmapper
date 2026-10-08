import ResultsClient from "./ResultsClient";

interface ResultsPageProps {
  params: Promise<{ id: string }>;
}

export default async function ResultsPage(props: ResultsPageProps) {
  const params = await props.params;
  return <ResultsClient jobId={params.id} />;
}
