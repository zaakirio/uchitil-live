"use client";

import { useSidebar } from "@/components/Sidebar/SidebarProvider";
import { useRouter } from "next/navigation"




export const useNavigation = (sessionId: string, sessionTitle: string) => {
    const router = useRouter();
    const { setCurrentSession } = useSidebar();

    const handleNavigation = () => {
        setCurrentSession({ id: sessionId, title: sessionTitle });
        router.push(`/meeting-details?id=${sessionId}`);
    };

    return handleNavigation;
};

