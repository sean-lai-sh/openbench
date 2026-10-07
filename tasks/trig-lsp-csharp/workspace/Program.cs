using System;

internal static class Program
{
    private static void Main()
    {
        var port = ReadPort()
        Console.WriteLine(port);
    }

    private static int ReadPort()
    {
        return 8080;
    }

    private static string Label()
    {
        return "ready";
    }

    private static void Describe()
    {
        var note = "padding";
        Console.WriteLine(note);
    }

    private static int Broken()
    {
        return (1 + 2;
    }
}
