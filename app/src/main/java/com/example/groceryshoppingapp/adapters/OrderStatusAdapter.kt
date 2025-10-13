//package com.example.groceryshoppingapp.adapters
//
//import android.view.LayoutInflater
//import android.view.View
//import android.view.ViewGroup
//import android.widget.Button
//import android.widget.TextView
//import androidx.recyclerview.widget.RecyclerView
//import com.example.groceryshoppingapp.R
//
//class OrderStatusAdapter(
//    private val orderList: List<String>,
//    private val onStatusClick: (String) -> Unit
//) : RecyclerView.Adapter<OrderStatusAdapter.OrderStatusViewHolder>() {
//
//    class OrderStatusViewHolder(view: View) : RecyclerView.ViewHolder(view) {
//        val orderId: TextView = view.findViewById(R.id.order_id)
//        val orderDetails: TextView = view.findViewById(R.id.order_details)
//        val statusButton: Button = view.findViewById(R.id.status_button)
//    }
//
//    override fun onCreateViewHolder(parent: ViewGroup, viewType: Int): OrderStatusViewHolder {
//        val view = LayoutInflater.from(parent.context)
//            .inflate(R.layout.item_order_status, parent, false)
//        return OrderStatusViewHolder(view)
//    }
//
//    override fun onBindViewHolder(holder: OrderStatusViewHolder, position: Int) {
//        val order = orderList[position]
//
//        holder.orderId.text = "Order #${position + 1}"
//        holder.orderDetails.text = order  // Assuming order is a string like "2 Apples, 1 Milk"
//        holder.statusButton.text = "Mark as Packed"
//
//        holder.statusButton.setOnClickListener {
//            onStatusClick(order)
//        }
//    }
//
//    override fun getItemCount(): Int = orderList.size
//}
