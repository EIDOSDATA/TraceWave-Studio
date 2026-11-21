using CADability;
using CADability.GeoObject;
using System.Text.Json;

/** @brief 독립 STEP 리더가 복원한 고체의 경계, 열린 모서리와 원통 면을 기록한다. */
internal static class StepReceiver
{
    private static object Bounds(BoundingCube box)
    {
        return new { minimum = new[] { box.Xmin, box.Ymin, box.Zmin }, maximum = new[] { box.Xmax, box.Ymax, box.Zmax } };
    }

    internal static int Main(string[] args)
    {
        if (args.Length != 1)
        {
            return 2;
        }
        var import = new ImportStep { HierarchyToBlocks = false };
        var objects = import.Read(args[0]);
        var solids = new List<object>();
        var others = new List<string>();
        foreach (IGeoObject shape in objects)
        {
            if (shape is not Solid solid)
            {
                others.Add(shape.GetType().Name);
                continue;
            }
            var cylinders = new List<object>();
            var planarFaces = new List<object>();
            foreach (var shell in solid.Shells)
            {
                foreach (var face in shell.Faces)
                {
                    if (face.Surface is PlaneSurface)
                    {
                        planarFaces.Add(new { holes = face.Area.Holes.Length, extent = Bounds(face.GetBoundingCube()) });
                    }
                    if (face.Surface is CylindricalSurface cylinder)
                    {
                        var axis = cylinder.Axis;
                        var location = cylinder.Location;
                        cylinders.Add(new
                        {
                            radius = cylinder.RadiusX,
                            axis = new[] { axis.x, axis.y, axis.z },
                            location = new[] { location.x, location.y, location.z },
                            extent = Bounds(face.GetBoundingCube()),
                        });
                    }
                }
            }
            solids.Add(new
            {
                name = solid.NameOrEmpty,
                extent = Bounds(solid.GetBoundingCube()),
                open_edges = solid.Shells.Sum(shell => shell.OpenEdges.Length),
                cylinders,
                planar_faces = planarFaces,
            });
        }
        Console.WriteLine(JsonSerializer.Serialize(new { solids, others }));
        return solids.Count > 0 ? 0 : 3;
    }
}
